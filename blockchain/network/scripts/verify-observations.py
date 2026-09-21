#!/usr/bin/env python3
import json
import sys
from pathlib import Path

def verify(directory, anchor_id=''):
    states=[]
    records=[]
    print('Node\tPeer\tChannel\tHeight\tCurrent block hash (base64)\tPrevious block hash (base64)')
    for number in range(1,5):
        node=f'node{number}'
        text=(directory/f'{node}.info').read_text()
        info=json.loads(text[text.index('{'):])
        state=(info['height'],info['currentBlockHash'],info['previousBlockHash'])
        if int(info['height'])<1:
            raise ValueError('Peer has no channel block.')
        states.append(state)
        print(f'{node}\t{node}.labchain.internal:7051\tlabchain-channel\t'+ '\t'.join(map(str,state)))
        if anchor_id:
            record=json.loads((directory/f'{node}.record').read_text())
            if record['anchor_id']!=anchor_id or not record.get('transaction_id'):
                raise ValueError('Unexpected anchor response.')
            records.append(record)
    if any(s!=states[0] for s in states):
        raise ValueError('Block heights or hashes have not converged.')
    if records and any(r!=records[0] for r in records):
        raise ValueError('Peer anchor records differ.')
    return records[0] if records else None

if __name__=='__main__':
    try:
        verify(Path(sys.argv[1]),sys.argv[2] if len(sys.argv)>2 else '')
    except (ValueError,KeyError,OSError) as error:
        sys.exit(str(error))
