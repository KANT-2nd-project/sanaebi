#!/bin/bash
# Run from a reviewed source checkout on the host as root. Secrets are preserved.
set -euo pipefail
test "$(id -u)" = 0
cd "$(dirname "$0")/.."
install -d -m 700 /etc/sanaebi /etc/sanaebi/docker-auth
install -d -m 755 /usr/local/libexec/sanaebi/scripts /srv/sanaebi/releases /srv/sanaebi/models /srv/sanaebi/assets
install -d -m 755 -o root -g root /var/lib/sanaebi
install -d -m 750 -o 10001 -g 10001 /var/lib/sanaebi/runtime
install -d -m 700 -o root -g root /var/lib/sanaebi/backups
for name in api.env hf-download.env; do
    if ! test -e "/etc/sanaebi/$name"; then
        install -m 600 /dev/null "/etc/sanaebi/$name"
    fi
done
for name in deploy_release.py production_maintenance.py; do
    install -o root -g root -m 750 "scripts/$name" "/usr/local/libexec/sanaebi/scripts/$name"
done
install -m 600 deployment/compose.production.yaml /etc/sanaebi/compose.yaml
install -m 750 scripts/registry_auth.py /usr/local/sbin/sanaebi-registry-auth
install -m 750 scripts/activate_production_nginx.sh /usr/local/sbin/sanaebi-activate-nginx
cat > /usr/local/sbin/sanaebi-deploy <<'WRAPPER'
#!/bin/sh
exec /usr/bin/python3 /usr/local/libexec/sanaebi/scripts/deploy_release.py "$@"
WRAPPER
chmod 750 /usr/local/sbin/sanaebi-deploy
rules=$(mktemp)
trap 'rm -f "$rules"' EXIT
cat > "$rules" <<'SUDOERS'
deploy ALL=(root) NOPASSWD: /usr/local/sbin/sanaebi-deploy deploy *, /usr/local/sbin/sanaebi-registry-auth login, /usr/local/sbin/sanaebi-registry-auth logout, /usr/local/sbin/sanaebi-activate-nginx ""
SUDOERS
visudo -cf "$rules"
install -m 440 "$rules" /etc/sudoers.d/sanaebi-deploy
for name in production api response-headers; do
    install -m 644 "deployment/nginx-$name.conf" "/etc/nginx/snippets/sanaebi-$name.conf"
done
# Stage the vhost; activate only after the first healthy release exists.
install -m 600 deployment/nginx-vhost.conf /etc/sanaebi/nginx-vhost.pending
install -m 644 deployment/systemd/sanaebi-production-* /etc/systemd/system/
systemctl daemon-reload
echo 'Trusted helpers installed; existing nginx vhost and timer activation preserved.'
