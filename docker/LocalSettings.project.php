<?php
# Project-specific settings, kept in git (no secrets here).
# Loaded from the server's LocalSettings.php with:
#   require_once "$IP/LocalSettings.project.php";

if ( !defined( 'MEDIAWIKI' ) ) {
	exit;
}

$wgDefaultSkin = 'vector-2022';

# Keep sessions and parsed pages in the database. With only APCu, a bulk upload
# fills the small shared cache, sessions are evicted and the bot is logged out.
$wgSessionCacheType = CACHE_DB;
$wgParserCacheType = CACHE_DB;
$wgEnableUploads = false;

# Structured data and forms
wfLoadExtension( 'Cargo' );
wfLoadExtension( 'PageForms' );

# Changes become visible only after a curator approves them
wfLoadExtension( 'ApprovedRevs' );
