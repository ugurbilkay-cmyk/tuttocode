"""Preserved vendor exports and explicit, staff-attested review evidence."""
import hashlib
import io
import time
import warnings

from PIL import Image, ImageOps

from . import config, photomatic, processing

STATES = {'pass': 'Pass', 'caution': 'Caution', 'fail': 'Fail', 'not_tested': 'Not tested'}
GROUPS = [('image_quality', 'Image quality'), ('geometry', 'Face size and position'), ('background', 'Background')]
METRICS = [
    ('confidence', 'Measurement confidence'), ('general_quality', 'General image quality'),
    ('eye1', 'Eye 1 position · pixels'), ('eye2', 'Eye 2 position · pixels'),
    ('eye_angle', 'Horizontal eye alignment · degrees'), ('eye_distance', 'Inter-eye distance · pixels'),
    ('pose', 'Pose'), ('face_biometrics', 'Face biometrics detectable'),
    ('eye_details', 'Eye details detectable'), ('biometric_details', 'Biometric details in image'),
    ('eyes_open', 'Eyes open'), ('eye_darkness', 'Sunglasses / darkness around eyes'),
    ('glare', 'Glare from glasses'), ('expression', 'Neutral expression'),
    ('mouth', 'Mouth closed'), ('smiling', 'Smiling'), ('sharpness', 'Sharpness'),
    ('motion_blur', 'Motion blur'), ('contrast', 'Contrast'), ('artefacts', 'Artefacts'),
    ('noise', 'Noise'), ('compression', 'Compression'), ('under_exposed', 'Under exposed'),
    ('over_exposed', 'Over exposed'), ('skin_colour', 'Natural skin colour'), ('hotspots', 'Hotspots'),
    ('uniform_lighting', 'Uniform lighting'), ('eye_shadow', 'Shadow in eyes'),
    ('face_shadow', 'Shadow in face'), ('red_eye', 'Red eyes'), ('glasses', 'Glasses'),
    ('face_height', 'Face height · percent / mm'), ('face_width', 'Face width · percent / mm'),
    ('eye_height', 'Eye height · percent from top'),
    ('background_bright', 'Background too bright'), ('background_dark', 'Background too dark'),
    ('background_uniform', 'Background uniformity'), ('background_shadows', 'Background shadows'),
    ('age_estimate', 'Age estimate'), ('gender', 'Gender'),
]


def inspect(data):
    """Decode for validation, preserving the original JPEG byte sequence."""
    if not data or len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError('Choose a JPEG within the upload limit')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != 'JPEG' or image.width * image.height > 40_000_000:
                    raise ValueError('Choose a digital JPEG portrait of at most 40 million pixels')
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                orientation = image.getexif().get(274, 1)
                if not isinstance(orientation, int) or orientation not in range(1, 9):
                    raise ValueError('The JPEG has an invalid orientation tag. Export a new digital portrait.')
                display = ImageOps.exif_transpose(image)
                return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                        'encoded_size': list(image.size), 'display_size': list(display.size),
                        'mode': image.mode, 'exif_orientation': orientation}
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('The file is not a complete readable JPEG portrait') from exc


def preview(data, bounds=(900, 1200)):
    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image).convert('RGB')
        image.thumbnail(bounds, Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, 'JPEG', quality=92)
        return out.getvalue()


def initial(data, parent=None):
    return {'version': 1, 'file': inspect(data), 'imported_at': time.time(),
            'parent': parent, 'reviewed': False,
            'groups': {key: 'not_tested' for key, _ in GROUPS},
            'metrics': {key: {'value': '', 'status': 'not_tested'} for key, _ in METRICS}}


def verify(data, record):
    current = inspect(data)
    if current != record['file']:
        raise ValueError('The imported JPEG changed. Import and review the new file.')
    return current


def checks(record, country_id):
    file = record['file']
    values = [processing.Check('file', 'Preserved JPEG', 'pass',
                             f"{file['display_size'][0]} × {file['display_size'][1]} px · {file['bytes']} bytes")]
    profile = photomatic.country(country_id)
    if profile['code_service'] == 'uk':
        width, height = file['display_size']
        target = profile['digital_size']
        valid = width >= 600 and height >= 750 and 50_000 <= file['bytes'] <= 10_000_000
        if all(v > 0 for v in target):
            valid = valid and [width, height] == target
        valid = valid and file['mode'] in ('RGB', 'L') and file['exif_orientation'] == 1
        values.append(processing.Check('delivery_format', 'UK digital file specification', 'pass' if valid else 'fail',
            'Dimensions and encoding are checked without resizing. Staff may proceed under responsibility if this is red.'))
    for key, label in GROUPS:
        status = record['groups'][key]
        values.append(processing.Check('photomatic_' + key, label + ' · staff recorded',
            'pass' if status == 'pass' else 'fail' if status == 'fail' else 'warn', STATES[status]))
    for key, label in METRICS:
        metric = record['metrics'][key]
        if metric['status'] == 'fail':
            values.append(processing.Check('photomatic_' + key, label + ' · staff recorded', 'fail', metric['value']))
    if record.get('parent'):
        for check in record['parent'].get('preparation_checks', []):
            if check['key'] == 'resolution' and check['status'] == 'fail':
                values.append(processing.Check('source_resolution', 'Camera detail before Photomatic', 'fail', check['detail']))
    return values


def needs_responsibility(record, country_id):
    return (not record['reviewed'] or any(s in ('fail', 'not_tested') for s in record['groups'].values())
            or any(c.status == 'fail' for c in checks(record, country_id)))


def reviewed(record, form, account, revision):
    out = dict(record)
    for key, limit in [('operator', 100), ('software_version', 100), ('vendor_profile', 200),
                       ('quality_profile', 200), ('review_notes', 2000)]:
        value = str(form.get(key) or '').strip()
        if len(value) > limit:
            raise ValueError(f'{key.replace("_", " ")} is too long')
        out[key] = value
    if not out['operator'] or not out['vendor_profile']:
        raise ValueError('Record the operator name and the selected Photomatic document profile')
    confirmations = ['review_export', 'review_document', 'review_likeness', 'review_visibility', 'customer_permission']
    if any(form.get(key) != 'on' for key in confirmations):
        raise ValueError('Complete the final exported photo review and customer permission')
    def state(key):
        value = form.get(key, 'not_tested')
        if value not in STATES:
            raise ValueError('Choose Pass, Caution, Fail or Not tested')
        return value
    out['groups'] = {key: state('group_' + key) for key, _ in GROUPS}
    out['metrics'] = {}
    for key, _ in METRICS:
        value = str(form.get('metric_' + key) or '').strip()
        if len(value) > 100:
            raise ValueError('A measurement value is too long')
        out['metrics'][key] = {'value': value, 'status': state('status_' + key)}
    context = form.get('decision_context', 'normal')
    if context not in ('normal', 'child', 'disability', 'health', 'other'):
        raise ValueError('Choose a valid decision context')
    out.update(reviewed=True, account=account, reviewed_at=time.time(), review_revision=revision,
               evidence_source='staff_attested_photomatic', confirmations=confirmations, decision_context=context)
    return out
