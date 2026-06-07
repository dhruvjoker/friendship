from datetime import datetime

from flask import request

from app.content_safety import detect_moderation_signals
from app.models import AbuseReport, SafetyEvent, UserIPLog, db


MODERATION_SOURCE_FIELDS = {
    'login': 'authentication',
    'register': 'authentication',
    'message': 'chat',
    'report': 'reporting',
}


def get_client_ip():
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def get_geo_metadata():
    return {
        'country': request.headers.get('CF-IPCountry') or request.headers.get('X-Geo-Country'),
        'region': request.headers.get('X-Geo-Region'),
        'city': request.headers.get('X-Geo-City'),
        'isp': request.headers.get('X-Geo-ISP') or request.headers.get('X-Forwarded-For-ISP'),
        'asn': request.headers.get('X-Geo-ASN'),
        'vpn_detected': request.headers.get('X-Geo-VPN', '').lower() == 'true',
    }


def record_user_ip(user_id, source='request'):
    if not user_id:
        return None

    metadata = get_geo_metadata()
    record = UserIPLog(
        user_id=user_id,
        ip_address=get_client_ip(),
        country=metadata.get('country'),
        region=metadata.get('region'),
        city=metadata.get('city'),
        isp=metadata.get('isp'),
        asn=metadata.get('asn'),
        vpn_detected=metadata.get('vpn_detected') or False,
        user_agent=request.headers.get('User-Agent'),
        source=MODERATION_SOURCE_FIELDS.get(source, source),
    )
    db.session.add(record)
    db.session.commit()
    return record


def severity_for_signal(category):
    if category == 'crisis':
        return 'high'
    if category == 'harassment':
        return 'high'
    if category == 'scam':
        return 'medium'
    return 'low'


def create_safety_events(user_id, content, message_id=None):
    if not content:
        return []

    events = []
    for category, matches in detect_moderation_signals(content):
        event = SafetyEvent(
            user_id=user_id,
            event_type='keyword',
            severity=severity_for_signal(category),
            details=f'{category}: {", ".join(matches)}',
            message_id=message_id,
            review_status='pending',
        )
        db.session.add(event)
        events.append(event)

    if events:
        db.session.commit()

    return events


def create_report(reporter_id, target_user_id, reason, details='', message_id=None):
    report = AbuseReport(
        reporter_id=reporter_id,
        target_user_id=target_user_id,
        message_id=message_id,
        reason=reason,
        details=details,
        status='pending',
    )
    db.session.add(report)
    db.session.commit()
    return report


def review_report(report_id, moderator_id, decision='resolved', resolution='Reviewed and closed'):
    report = AbuseReport.query.get(report_id)
    if not report:
        return None

    report.status = 'resolved' if decision != 'dismissed' else 'dismissed'
    report.reviewed_by = moderator_id
    report.reviewed_at = datetime.utcnow()
    report.resolution = resolution
    db.session.commit()
    return report


def review_safety_event(event_id, moderator_id, decision='reviewed'):
    event = SafetyEvent.query.get(event_id)
    if not event:
        return None

    event.review_status = 'reviewed' if decision != 'dismissed' else 'dismissed'
    event.reviewed_by = moderator_id
    event.reviewed_at = datetime.utcnow()
    db.session.commit()
    return event
