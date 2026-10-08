#!/usr/bin/env bash
# Start one backend service in a container and say how the integration tests reach it.
#
#   bash tests/integration/start_service.sh s3|azure|sftp|ftp|webdav|smb
#
# The FA_IT_* variables the tests read are appended to $GITHUB_ENV in GitHub
# Actions. Anywhere else they are printed as `export` lines:
#
#   eval "$(bash tests/integration/start_service.sh s3)"
#   python -m pytest tests/integration/test_s3_minio.py
#
# Every password and key is generated here, for this run only. Nothing is stored.
set -euo pipefail

service="${1:?usage: start_service.sh s3|azure|sftp|ftp|webdav|smb}"
user="fa"
secret="$(openssl rand -hex 16)"

emit() {
  if [ -n "${GITHUB_ENV:-}" ]; then
    printf '%s=%s\n' "$1" "$2" >> "$GITHUB_ENV"
  else
    printf 'export %s=%q\n' "$1" "$2"
  fi
}

wait_for_port() {
  local attempt
  for attempt in $(seq 1 90); do
    if (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "nothing is listening on 127.0.0.1:$1 after ${attempt}s" >&2
  docker ps -a >&2
  docker logs "fa-it-$service" >&2 || true
  return 1
}

case "$service" in
  s3)
    docker run -d --name fa-it-s3 -p 9000:9000 \
      -e "MINIO_ROOT_USER=$user-integration" -e "MINIO_ROOT_PASSWORD=$secret" \
      minio/minio server /data >&2
    wait_for_port 9000
    emit FA_IT_S3_ENDPOINT "http://127.0.0.1:9000"
    emit FA_IT_S3_ACCESS_KEY "$user-integration"
    emit FA_IT_S3_SECRET_KEY "$secret"
    ;;
  azure)
    account="faintegration"
    key="$(openssl rand -base64 32)"
    docker run -d --name fa-it-azure -p 10000:10000 \
      -e "AZURITE_ACCOUNTS=$account:$key" \
      mcr.microsoft.com/azure-storage/azurite \
      azurite-blob --blobHost 0.0.0.0 --skipApiVersionCheck >&2
    wait_for_port 10000
    emit FA_IT_AZURE_CONNECTION_STRING \
      "DefaultEndpointsProtocol=http;AccountName=$account;AccountKey=$key;BlobEndpoint=http://127.0.0.1:10000/$account;"
    ;;
  sftp)
    docker run -d --name fa-it-sftp -p 2222:22 atmoz/sftp "$user:$secret:1001::upload" >&2
    wait_for_port 2222
    known_hosts="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/fa-it-known-hosts"
    # The port accepts connections a moment before sshd hands out its keys.
    for _ in $(seq 1 30); do
      ssh-keyscan -p 2222 127.0.0.1 > "$known_hosts" 2>/dev/null || true
      [ -s "$known_hosts" ] && break
      sleep 1
    done
    [ -s "$known_hosts" ] || { echo "the SFTP server offered no host key" >&2; exit 1; }
    emit FA_IT_SFTP_HOST 127.0.0.1
    emit FA_IT_SFTP_PORT 2222
    emit FA_IT_SFTP_USER "$user"
    emit FA_IT_SFTP_PASSWORD "$secret"
    emit FA_IT_SFTP_KNOWN_HOSTS "$known_hosts"
    emit FA_IT_SFTP_ROOT /upload
    ;;
  ftp)
    docker run -d --name fa-it-ftp -p 2121:21 -p 21000-21010:21000-21010 \
      -e "USERS=$user|$secret" -e ADDRESS=127.0.0.1 -e MIN_PORT=21000 -e MAX_PORT=21010 \
      delfer/alpine-ftp-server >&2
    wait_for_port 2121
    emit FA_IT_FTP_HOST 127.0.0.1
    emit FA_IT_FTP_PORT 2121
    emit FA_IT_FTP_USER "$user"
    emit FA_IT_FTP_PASSWORD "$secret"
    ;;
  webdav)
    docker run -d --name fa-it-webdav -p 8080:80 \
      -e AUTH_TYPE=Basic -e "USERNAME=$user" -e "PASSWORD=$secret" \
      bytemark/webdav >&2
    wait_for_port 8080
    emit FA_IT_WEBDAV_URL "http://127.0.0.1:8080"
    emit FA_IT_WEBDAV_USER "$user"
    emit FA_IT_WEBDAV_PASSWORD "$secret"
    ;;
  smb)
    docker run -d --name fa-it-smb -p 4450:445 \
      dperson/samba -p -u "$user;$secret" -s "share;/share;yes;no;no;$user" >&2
    wait_for_port 4450
    emit FA_IT_SMB_SERVER 127.0.0.1
    emit FA_IT_SMB_PORT 4450
    emit FA_IT_SMB_SHARE share
    emit FA_IT_SMB_USER "$user"
    emit FA_IT_SMB_PASSWORD "$secret"
    ;;
  *)
    echo "unknown service: $service" >&2
    exit 2
    ;;
esac
