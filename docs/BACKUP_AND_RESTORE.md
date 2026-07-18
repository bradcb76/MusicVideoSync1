# Backup and restore

Stop Compose before copying `data\music-video-sync.db`. Verify source and backup with
`Get-FileHash -Algorithm SHA256`. Startup also creates a pre-migration backup. Preserve the current
database before restoring a verified backup.
