#!/usr/bin/env python3
"""Sanitize config files - remove API keys from temp files."""
import re

def sanitize_file(src, dst):
    with open(src, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace all API keys with empty strings
    patterns = [
        (r'"api_key"\s*:\s*"[^"]*"', '"api_key": ""'),
        (r'"sdk_api_key"\s*:\s*"[^"]*"', '"sdk_api_key": ""'),
        (r'"hf_token"\s*:\s*"[^"]*"', '"hf_token": ""'),
    ]
    
    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content)
    
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'Updated: {dst}')

configs = ['asr_interfaces.json', 'tts_interfaces.json', 'imagegen_interfaces.json', 'videogen_interfaces.json']
for cfg in configs:
    src = f'backend/config/{cfg}'
    dst = f'backend/config/{cfg}.temp'
    try:
        sanitize_file(src, dst)
    except Exception as e:
        print(f'Error processing {cfg}: {e}')

print('Done!')
