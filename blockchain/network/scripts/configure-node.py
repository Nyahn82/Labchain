#!/usr/bin/env python3
"""Write one validated per-VPS .env; never overwrite existing configuration."""
import argparse
import tempfile
from pathlib import Path
from config import read_config

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('node', choices=['node1', 'node2', 'node3', 'node4'])
parser.add_argument('ips', nargs=4, metavar='IP', help='Fixed routable IPv4 addresses for nodes 1, 2, 3, 4, in order.')
parser.add_argument('--bind-ip', help='Local interface address if different from the advertised IP (NAT).')
args = parser.parse_args()
network = Path(__file__).resolve().parents[1]
number = int(args.node[-1])
values = {
    'NODE_ID': args.node, 'NODE_PUBLIC_IP': args.ips[number-1],
    'NODE_BIND_IP': args.bind_ip or args.ips[number-1],
    'ORG_ID': 'Org1MSP' if number <= 2 else 'Org2MSP',
    'PEER_HOSTNAME': f'{args.node}.labchain.internal',
    **{f'NODE{i+1}_IP': ip for i, ip in enumerate(args.ips)},
}
lines = []
for line in (network/'.env.example').read_text().splitlines():
    key = line.split('=', 1)[0]
    lines.append(f'{key}={values[key]}' if key in values else line)
text = '\n'.join(lines)+'\n'
with tempfile.NamedTemporaryFile(mode='w+', encoding='utf8') as check:
    check.write(text)
    check.flush()
    read_config(check.name)
try:
    with (network/'.env').open('x', encoding='utf8') as output:
        output.write(text)
    (network/'.env').chmod(0o600)
except FileExistsError:
    parser.exit(1, 'Existing .env retained. Review and edit it explicitly if configuration changed.\n')
print(f'Configured {args.node}. FIREWALL_READY stays no until the administrator verifies firewall rules.')
