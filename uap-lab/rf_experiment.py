"""RF experiment preflight. This module deliberately has no hardware execution path."""
import hashlib

PROFILES = (
    ('simulation', 'Simulation / dry run', 'Checks UTF-8 encoding without transmitting RF.'),
    ('shielded', 'Shielded bench test', 'Actual RF: requires verified shielding or a terminated, attenuated test path.'),
    ('ham-technician', 'Ham — Technician', 'Requires a designated control operator and station limits within Technician privileges.'),
    ('ham-general', 'Ham — General', 'Requires a designated control operator and station limits within General privileges.'),
    ('ham-extra', 'Ham — Amateur Extra', 'Requires a designated control operator and station limits within Amateur Extra privileges.'),
    ('experimental', 'Experimental authorization (not supported)', 'Grant-specific transmit channels are not supported in this release.'),
)

def preset(profile):
    # NCPA Northern California digital plan: 441.50 MHz, any digital.
    # A proposed default, not channel clearance or an authorization to radiate.
    if profile.startswith('ham-') or profile=='shielded':
        return dict(frequency_hz=441500000, state='operator-review-required', label='441.500 MHz preset')
    return dict(frequency_hz=None,state='no-rf' if profile=='simulation' else 'grant-required',label='No RF output' if profile=='simulation' else 'Frequency defined by the experimental grant')

def status():
    return dict(transmit_enabled=False, profiles=[dict(id=key,label=label,description=description,preset=preset(key),transmit_enabled=False) for key,label,description in PROFILES], reason='Complete Operator setup and arm a supervised session before transmitting.')

def prepare(value):
    if not isinstance(value,dict):raise ValueError('Expected an experiment request.')
    profile=value.get('profile','simulation')
    if profile not in {p[0] for p in PROFILES}:raise ValueError('Unknown operating profile.')
    if value.get('action','preview')!='preview':raise ValueError('RF transmission is locked. Only a dry run is available.')
    # Reject attempts to smuggle hardware settings into a dry-run request.
    if set(value)-{'profile','message','action'}:raise ValueError('Hardware settings are not accepted by the dry-run endpoint.')
    message=value.get('message')
    if not isinstance(message,str) or not message.strip():raise ValueError('Enter a message.')
    payload=message.encode('utf-8')
    if len(payload)>256:raise ValueError('Use at most 256 UTF-8 bytes.')
    if any(ord(c)<32 and c not in '\n\t' for c in message):raise ValueError('Remove control characters from the message.')
    return dict(profile=profile,preset=preset(profile),mode='dry-run',transmitted=False,encoding='UTF-8',bytes=len(payload),bits=len(payload)*8,hex=payload.hex(' '),sha256=hashlib.sha256(payload).hexdigest(),message='Dry run complete. No RF transmitted. This checks payload encoding, not modulation or reception.')
