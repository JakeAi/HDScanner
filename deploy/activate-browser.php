<?php
// Run on Unraid only after both images and the private browser service pass checks.
$base='/mnt/user/appdata/hdscanner';
$backup=$base.'/backups/pre-browser-20261008';
$c=json_decode(file_get_contents($backup.'/container.json'),true,512,JSON_THROW_ON_ERROR)[0];
if ($c['Config']['Image']!=='hdscanner:dashboard' || count($c['Mounts'])!==1
    || $c['HostConfig']['NetworkMode']!=='bridge') throw new RuntimeException('Unexpected original container settings');
$env=file_get_contents($base.'/data/.env');
$settings=['HTTP_TRANSPORT'=>'browser','BROWSER_SERVICE_URL'=>'http://hdscanner-browser:4010',
 'BROWSER_TOKEN_FILE'=>'.hd_browser_token','BROWSER_TIMEOUT_SECONDS'=>'120','MAX_ATTEMPTS'=>'1',
 'UNRAID_CRON_PATH'=>'/host-cron/root','SCAN_HOURS_ET'=>'4,12,20','SCAN_MINUTE'=>'17'];
foreach ($settings as $key=>$value) {
 $env=preg_replace('/^'.preg_quote($key,'/').'=.*(?:\r?\n|$)/m','',$env);
 $env=rtrim($env,"\r\n")."\n$key=$value\n";
}
umask(0077);
file_put_contents($base.'/data/.env',$env);
$lines=[];
foreach($c['Config']['Env'] as $line) {
 if(str_contains($line,"\n")||str_contains($line,"\r"))throw new RuntimeException('Multiline container env requires review');
 [$key]=explode('=',$line,2);
 if(!array_key_exists($key,$settings))$lines[]=$line;
}
foreach($settings as $key=>$value)$lines[]="$key=$value";
file_put_contents($backup.'/container.env',implode("\n",$lines)."\n");
$args=['docker','run','-d','--name','hdscanner','--restart','unless-stopped','--network','hdscanner-browser-network','--env-file',$backup.'/container.env'];
foreach($c['Mounts'] as $m)array_push($args,'-v',$m['Source'].':'.$m['Destination'].($m['RW']?':rw':':ro'));
array_push($args,'-v','/etc/cron.d:/host-cron:ro');
foreach(['hdscanner','hdscanner-prune'] as $job) {
 $directory='/boot/config/plugins/user.scripts/scripts/'.$job;
 if(!is_file($directory.'/script'))throw new RuntimeException('Expected Unraid script is missing');
 array_push($args,'-v',$directory.':'.$directory.':ro');
}
foreach($c['HostConfig']['PortBindings'] as $containerPort=>$bindings)foreach($bindings as $p)
 array_push($args,'-p',($p['HostIp']!==''?$p['HostIp'].':':'').$p['HostPort'].':'.$containerPort);
foreach($c['Config']['Labels']??[] as $key=>$value)array_push($args,'--label',"$key=$value");
if(!empty($c['Config']['User']))array_push($args,'--user',$c['Config']['User']);
if(!empty($c['Config']['WorkingDir']))array_push($args,'-w',$c['Config']['WorkingDir']);
if($c['Config']['Entrypoint']!==['hd'])throw new RuntimeException('Unexpected entrypoint');
array_push($args,'--entrypoint','hd','hdscanner:browser',...$c['Config']['Cmd']);
$command=implode(' ',array_map('escapeshellarg',$args));
file_put_contents($base.'/browser-source/start-scanner.sh',"#!/bin/bash\nset -eu\n$command\n");
echo "Browser settings prepared; original container configuration backed up privately.\n";
