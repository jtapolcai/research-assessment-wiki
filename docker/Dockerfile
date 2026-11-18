# MediaWiki 1.43 (LTS) with the extensions this project needs.
FROM mediawiki:1.43

# Pinned extension versions (all checked against MediaWiki >= 1.42).
ARG CARGO_VERSION=3.9.5
ARG PAGEFORMS_VERSION=6.0.11
ARG APPROVEDREVS_VERSION=2.4.3

RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/* \
 && cd /var/www/html/extensions \
 && git clone --depth 1 --branch "${CARGO_VERSION}" \
      https://gerrit.wikimedia.org/r/mediawiki/extensions/Cargo Cargo \
 && git clone --depth 1 --branch "${PAGEFORMS_VERSION}" \
      https://gerrit.wikimedia.org/r/mediawiki/extensions/PageForms PageForms \
 && git clone --depth 1 --branch "${APPROVEDREVS_VERSION}" \
      https://gerrit.wikimedia.org/r/mediawiki/extensions/ApprovedRevs ApprovedRevs \
 && rm -rf Cargo/.git PageForms/.git ApprovedRevs/.git

# Upload security: serve files from the upload directory with "nosniff".
RUN a2enmod headers \
 && printf '<Directory /var/www/html/images>\n  Header set X-Content-Type-Options "nosniff"\n</Directory>\n' \
      > /etc/apache2/conf-enabled/uploads-nosniff.conf
