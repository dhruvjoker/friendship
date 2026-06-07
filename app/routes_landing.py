"""
routes_landing.py — Landing page, legal pages, and contact form routes.
"""

import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import current_user

logger = logging.getLogger(__name__)

landing_bp = Blueprint('landing', __name__)


@landing_bp.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('landing.html')


@landing_bp.route('/sitemap.xml')
def sitemap():
    from flask import make_response, current_app
    import os
    sitemap_path = os.path.join(current_app.root_path, '..', 'sitemap.xml')
    try:
        with open(sitemap_path) as f:
            content = f.read()
    except FileNotFoundError:
        content = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
    resp = make_response(content)
    resp.headers['Content-Type'] = 'application/xml'
    return resp


@landing_bp.route('/robots.txt')
def robots():
    from flask import make_response, current_app
    import os
    robots_path = os.path.join(current_app.root_path, '..', 'robots.txt')
    try:
        with open(robots_path) as f:
            content = f.read()
    except FileNotFoundError:
        content = 'User-agent: *\nDisallow: /auth/\nDisallow: /api/\nDisallow: /admin/\nAllow: /'
    resp = make_response(content)
    resp.headers['Content-Type'] = 'text/plain'
    return resp


@landing_bp.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy_policy.html')


@landing_bp.route('/terms-of-service')
def terms_of_service():
    return render_template('terms_of_service.html')


@landing_bp.route('/community-guidelines')
def community_guidelines():
    return render_template('community_guidelines.html')


@landing_bp.route('/contact')
def contact():
    return render_template('contact.html')


@landing_bp.route('/contact/submit', methods=['POST'])
def contact_submit():
    email    = request.form.get('email', '').strip()
    category = request.form.get('category', '').strip()
    subject  = request.form.get('subject', '').strip()
    message  = request.form.get('message', '').strip()

    if not all([email, category, subject, message]):
        return jsonify({'error': 'All fields are required.'}), 400
    if len(message) > 5000:
        return jsonify({'error': 'Message too long (max 5000 characters).'}), 400

    try:
        from app.email_service import send_contact_form_email
        send_contact_form_email(email, category, subject, message)
    except Exception:
        logger.exception("Failed to forward contact form email")

    logger.info("Contact form: category=%s domain=%s", category, email.split('@')[-1] if '@' in email else 'unknown')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True})
    flash("Your message has been sent. We'll get back to you within 2 business days.", 'success')
    return redirect(url_for('landing.contact'))
