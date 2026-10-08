FROM actual-receipt-companion-crawler:local
COPY --chown=node:node browser /app/hd-browser
ENV CRAWLER_DATA_DIR=/browser-data CLOAKBROWSER_CACHE_DIR=/browser-data/cloakbrowser-cache
ENTRYPOINT ["tini", "--"]
CMD ["bash", "/app/hd-browser/start.sh"]
