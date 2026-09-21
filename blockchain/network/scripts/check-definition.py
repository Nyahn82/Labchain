#!/usr/bin/env python3
"""Verify a committed lifecycle definition and its two-organization policy."""
import base64
import json
import subprocess
import sys


def decode(type_name, encoded):
    return json.loads(subprocess.check_output(
        ['configtxlator', 'proto_decode', '--type', type_name],
        input=base64.b64decode(encoded, validate=True)))


def validate(definition):
    if int(definition['sequence']) != 1 or definition['version'] != '1.0.0' or definition.get('init_required', False):
        raise ValueError('Existing definition differs from Phase 8A; an explicit upgrade is required.')
    # Lifecycle --signature-policy marshals peer.ApplicationPolicy, whose proto
    # package is "protos". Channel configuration uses SignaturePolicyEnvelope
    # directly; decoding lifecycle bytes as that envelope is incorrect.
    application = decode('protos.ApplicationPolicy', definition['validation_parameter'])
    if 'signature_policy' not in application:
        raise ValueError('Expected an explicit two-organization signature policy.')
    policy = application['signature_policy']
    roles = []
    for identity in policy['identities']:
        if identity['principal_classification'] != 'ROLE':
            raise ValueError('Unexpected endorsement principal.')
        principal = decode('common.MSPRole', identity['principal'])
        if principal['role'] != 'PEER':
            raise ValueError('Endorsement must require peer identities.')
        roles.append(principal['msp_identifier'])
    rule = policy['rule']['n_out_of']
    if sorted(roles) != ['Org1MSP', 'Org2MSP'] or rule['n'] != 2 or sorted(r['signed_by'] for r in rule['rules']) != [0, 1]:
        raise ValueError('Both organizations must endorse.')


if __name__ == '__main__':
    try:
        validate(json.load(sys.stdin))
    except (ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        sys.exit(f'Definition validation failed: {error}')
