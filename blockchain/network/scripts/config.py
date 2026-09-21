#!/usr/bin/env python3
"""Validate plain deployment configuration without evaluating shell input."""
import argparse
import ipaddress
import json
import re
import socket
import subprocess
from pathlib import Path

KEYS = {'NODE_ID','NODE_PUBLIC_IP','NODE_BIND_IP','ORG_ID','PEER_HOSTNAME',
        'PEER_LISTEN_PORT','PEER_CHAINCODE_PORT','ORDERER_HOST','ORDERER_PORT',
        'FABRIC_VERSION','NODE1_IP','NODE2_IP','NODE3_IP','NODE4_IP','FIREWALL_READY'}
EXAMPLES = [ipaddress.ip_network(v) for v in ['192.0.2.0/24','198.51.100.0/24','203.0.113.0/24']]

def read_config(path, allow_example=False):
    values = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if '=' not in line:
            raise ValueError('Expected plain KEY=value assignments.')
        key, value = line.split('=', 1)
        if key not in KEYS or key in values or not re.fullmatch(r'[A-Za-z0-9_.:-]+', value):
            raise ValueError('Unknown, duplicate or unsafe configuration assignment.')
        values[key] = value
    if set(values) != KEYS:
        raise ValueError('Missing required configuration variables.')
    if values['NODE_ID'] not in ('node1','node2','node3','node4'):
        raise ValueError('NODE_ID must be node1 through node4.')
    node = int(values['NODE_ID'][-1])
    expected = {'ORG_ID': 'Org1MSP' if node <= 2 else 'Org2MSP',
                'PEER_HOSTNAME': f'node{node}.labchain.internal',
                'NODE_PUBLIC_IP': values[f'NODE{node}_IP'],
                'PEER_LISTEN_PORT': '7051','PEER_CHAINCODE_PORT': '7052',
                'ORDERER_HOST': 'node4.labchain.internal','ORDERER_PORT': '7050',
                'FABRIC_VERSION': '2.5.16'}
    if any(values[k] != v for k,v in expected.items()):
        raise ValueError('Node identity, topology, ports or pinned version do not match this phase.')
    ips = [values[f'NODE{i}_IP'] for i in range(1,5)]
    if len(set(ips)) != 4:
        raise ValueError('Four distinct VPS IP addresses are required.')
    for raw in ips + [values['NODE_BIND_IP']]:
        ip = ipaddress.ip_address(raw)
        if ip.version != 4 or ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_link_local or ip.is_reserved:
            raise ValueError('Use a reachable fixed unicast IPv4 address.')
        if not allow_example and any(ip in network for network in EXAMPLES):
            raise ValueError('Replace documentation IP addresses before deployment.')
    if values['FIREWALL_READY'] not in ('yes','no'):
        raise ValueError('FIREWALL_READY must be yes or no.')
    return values

def check_host(values):
    for i in range(1,5):
        if socket.gethostbyname(f'node{i}.labchain.internal') != values[f'NODE{i}_IP']:
            raise ValueError('Host DNS/hosts mapping differs from the configured inventory.')
    interfaces = json.loads(subprocess.check_output(['ip','-j','address','show'], text=True))
    if not any(a.get('local') == values['NODE_BIND_IP'] for x in interfaces for a in x.get('addr_info',[])):
        raise ValueError('NODE_BIND_IP must be assigned to this VPS.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('env_file')
    parser.add_argument('--allow-example', action='store_true', help='Syntax checks only; never used by start scripts.')
    parser.add_argument('--host', action='store_true')
    args = parser.parse_args()
    try:
        config = read_config(args.env_file, args.allow_example)
        if args.host:
            check_host(config)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Configuration check failed: {error}\n')
