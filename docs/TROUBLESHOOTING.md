# Troubleshooting

Use `docker compose logs --tail 200` for startup errors. `not_ready` usually means a mount or database
permission problem. Test Plex and Emby independently; refresh failures do not fail completed downloads.
