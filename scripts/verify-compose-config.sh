#!/usr/bin/env bash
set -euo pipefail

config=$(docker compose config)
for service in analysis fenicsx rve; do
  grep -q "^  ${service}:" <<<"$config"
done
[[ $(grep -c 'host_ip: 127.0.0.1' <<<"$config") -eq 3 ]]
for port in 8888 8889 8890; do
  grep -q "published: \"${port}\"" <<<"$config"
done
grep -q 'JUPYTER_TOKEN' <<<"$config"
