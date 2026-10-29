// document.addEventListener('DOMContentLoaded', function () {
//     'use strict';

//     const cfg = window.BOOKING_CONFIG;
//     const roomMeta = JSON.parse(document.getElementById('room-data').textContent);
//     const $ = (id) => document.getElementById(id);
//     const enc = encodeURIComponent;

//     // ================= helpers =================
//     function escapeHtml(str) {
//         return String(str == null ? '' : str).replace(/[&<>"']/g, (c) =>
//             ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
//     }

//     function money(v) {
//         return '₹ ' + Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
//     }

//     function ordinal(day) {
//         return (day % 10 === 1 && day !== 11) ? 'st' : (day % 10 === 2 && day !== 12) ? 'nd' : (day % 10 === 3 && day !== 13) ? 'rd' : 'th';
//     }

//     function formatSummaryDate(ds) {
//         const d = new Date(ds + 'T00:00:00');
//         return d.getDate() + ordinal(d.getDate()) + ' ' + d.toLocaleDateString('en-GB', { month: 'short' }) + ' ' + d.getFullYear();
//     }

//     function formatDisplay(ds) {
//         const d = new Date(ds + 'T00:00:00');
//         return String(d.getDate()).padStart(2, '0') + ' ' + d.toLocaleDateString('en-GB', { month: 'short' }) + ' ' +
//             d.getFullYear() + ', ' + d.toLocaleDateString('en-GB', { weekday: 'short' });
//     }

//     function daysBetween(a, b) {
//         return Math.round((new Date(b + 'T00:00:00') - new Date(a + 'T00:00:00')) / 86400000);
//     }

//     // 31 Jan + 1 month = end of Feb (same rule as the server's add_months)
//     function addMonths(ds, m) {
//         const p = ds.split('-').map(Number);
//         const t = new Date(Date.UTC(p[0], p[1] - 1 + m, 1));
//         const last = new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth() + 1, 0)).getUTCDate();
//         t.setUTCDate(Math.min(p[2], last));
//         return t.toISOString().slice(0, 10);
//     }

//     function wholeMonths(ci, co) {
//         if (!ci || !co) return 0;
//         for (let m = 1; m <= 24; m++) { if (addMonths(ci, m) === co) return m; }
//         return 0;
//     }

//     function request(method, url, payload) {
//         const opts = { method: method, headers: { 'Accept': 'application/json' }, credentials: 'same-origin' };
//         if (method !== 'GET') {
//             opts.headers['Content-Type'] = 'application/json';
//             opts.headers['X-CSRFToken'] = cfg.csrf;
//             opts.body = JSON.stringify(payload || {});
//         }
//         return fetch(url, opts).then((r) =>
//             r.json().catch(() => ({})).then((data) => ({ ok: r.ok, status: r.status, data: data })));
//     }

//     // Flatten any API error body (custom {"error"} or DRF field errors) to one string.
//     function errorText(res) {
//         const d = res.data || {};
//         if (d.error && d.error.message) return d.error.message;
//         if (res.status === 429) return 'Too many requests. Please wait a moment and try again.';
//         const parts = [];
//         (function walk(v) {
//             if (typeof v === 'string') parts.push(v);
//             else if (Array.isArray(v)) v.forEach(walk);
//             else if (v && typeof v === 'object') Object.values(v).forEach(walk);
//         })(d);
//         return parts.length ? parts.join(' ') : 'Something went wrong. Please try again.';
//     }

//     // ================= state =================
//     const checkinInput = $('checkin-input');
//     const checkoutInput = $('checkout-input');
//     let selectedCheckin = checkinInput.dataset.date;
//     let selectedCheckout = checkoutInput.dataset.date;
//     let pickingCheckout = false;
//     let calOffset = 0;
//     let quote = null;            // last good server quote for the current cart
//     let inGuestView = false;
//     let submitting = false;
//     let availSeq = 0;
//     let quoteSeq = 0;

//     const cards = Array.from(document.querySelectorAll('.room-card'));
//     const btnMain = $('btn-main-action');

//     function currentDates() {
//         if (!selectedCheckin || !selectedCheckout || selectedCheckout <= selectedCheckin) return null;
//         return { check_in: selectedCheckin, check_out: selectedCheckout };
//     }

//     function selectedKeys() {
//         return cards.filter((c) => c.querySelector('.btn-toggle-room').classList.contains('added'))
//             .map((c) => c.dataset.key);
//     }

//     // ================= summary =================
//     function showSummaryError(msg) {
//         const el = $('summary-error');
//         el.textContent = msg;
//         el.style.display = msg ? 'block' : 'none';
//     }

//     function renderSummary() {
//         const dates = currentDates();
//         $('summary-rooms').textContent = quote ? quote.count : 0;
//         $('summary-guests').textContent = quote ? quote.guests : 0;
//         $('summary-nights').textContent = quote ? quote.nights : (dates ? daysBetween(dates.check_in, dates.check_out) : 1);
//         $('summary-total').textContent = money(quote ? quote.total : 0);
//         $('room-guest-select').options[0].textContent = quote
//             ? quote.count + ' Room' + (quote.count > 1 ? 's' : '') + ', ' + quote.guests + ' Adult' + (quote.guests > 1 ? 's' : '') + ', 0 Children'
//             : '0 Room, 0 Adult, 0 Children';
//     }

//     function updateSummaryDates() {
//         $('summary-checkin').textContent = selectedCheckin ? formatSummaryDate(selectedCheckin) : '-';
//         $('summary-checkout').textContent = selectedCheckout ? formatSummaryDate(selectedCheckout) : '-';
//     }

//     // The server is the only source of prices. On failure we show the message and no total.
//     function updateQuote() {
//         const keys = selectedKeys();
//         const dates = currentDates();
//         if (!keys.length) { quote = null; showSummaryError(''); renderSummary(); return Promise.resolve(); }
//         if (!dates) { quote = null; showSummaryError('Select your check-in and check-out dates.'); renderSummary(); return Promise.resolve(); }

//         const seq = ++quoteSeq;
//         const body = Object.assign({ items: keys.map((k) => ({ key: k, quantity: 1 })) }, dates);
//         return request('POST', cfg.urls.quote, body).then((res) => {
//             if (seq !== quoteSeq) return;                 // a newer request superseded this one
//             if (!res.ok) { quote = null; showSummaryError(errorText(res)); }
//             else { quote = res.data; showSummaryError(''); }
//             renderSummary();
//         }).catch(() => {
//             if (seq !== quoteSeq) return;
//             quote = null;
//             showSummaryError('Could not reach the server. Please try again.');
//             renderSummary();
//         });
//     }

//     // ================= availability =================
//     function refreshAvailability() {
//         const dates = currentDates();
//         if (!dates) { return updateQuote(); }
//         const seq = ++availSeq;
//         const url = cfg.urls.availability + '?check_in=' + enc(dates.check_in) + '&check_out=' + enc(dates.check_out);

//         return request('GET', url).then((res) => {
//             if (seq !== availSeq) return;
//             if (!res.ok) { showSummaryError(errorText(res)); return; }

//             const byKey = {};
//             res.data.properties.forEach((p) => p.room_types.forEach((rt) => { byKey[rt.key] = rt; }));
//             const removed = [];

//             cards.forEach((card) => {
//                 const rt = byKey[card.dataset.key];
//                 const units = rt ? rt.available_count : 0;
//                 const btn = card.querySelector('.btn-toggle-room');
//                 const note = card.querySelector('[data-avail-note]');
//                 const hold = card.querySelector('[data-holding]');
//                 card.querySelector('[data-units]').textContent = 'Units Available : ' + units;

//                 if (units < 1) {
//                     if (btn.classList.contains('added')) { btn.classList.remove('added'); removed.push(card.dataset.title); }
//                     card.classList.add('sold-out');
//                     btn.disabled = true;
//                     btn.textContent = 'SOLD OUT';
//                     note.textContent = 'No units available for these dates';
//                     note.className = 'availability-note none';
//                 } else {
//                     card.classList.remove('sold-out');
//                     if (!btn.classList.contains('added')) { btn.disabled = false; btn.textContent = 'ADD'; }
//                     if (units <= 2) {
//                         note.textContent = 'Only ' + units + ' unit(s) left for these dates';
//                         note.className = 'availability-note low';
//                     } else {
//                         note.textContent = '';
//                         note.className = 'availability-note';
//                     }
//                 }

//                 const holding = rt ? rt.holding_count : 0;       // real number of unexpired holds
//                 if (hold) {
//                     hold.hidden = !holding;
//                     hold.textContent = holding ? holding + (holding === 1 ? ' person is' : ' people are') + ' booking now' : '';
//                 }
//             });

//             if (removed.length) {
//                 alert('No longer available for these dates and removed from your selection: ' + removed.join(', '));
//             }
//             return updateQuote();
//         }).catch(() => {});
//     }

//     function onDatesChanged() {
//         updateSummaryDates();
//         refreshAvailability();
//     }

//     // ================= calendar =================
//     const calendarPopup = $('calendar-popup');
//     const calendarGrid = $('calendar-grid-container');

//     function buildMonth(y, m) {                           // m is 0-based
//         const first = new Date(Date.UTC(y, m, 1));
//         const offset = (first.getUTCDay() + 6) % 7;       // Monday first
//         const days = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
//         const title = first.toLocaleDateString('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' });
//         let h = '<div class="month-col"><div class="month-title">' + title + '</div>' +
//             '<div class="days-header"><span>Mo</span><span>Tu</span><span>We</span><span>Th</span><span>Fr</span><span>Sa</span><span>Su</span></div>' +
//             '<div class="days-grid">';
//         for (let i = 0; i < offset; i++) h += '<div class="date-cell disabled"></div>';
//         for (let d = 1; d <= days; d++) {
//             const ds = y + '-' + String(m + 1).padStart(2, '0') + '-' + String(d).padStart(2, '0');
//             h += '<div class="date-cell' + (ds < cfg.today ? ' disabled' : '') + '" data-date="' + ds + '">' + d + '<span class="price-sub"></span></div>';
//         }
//         return h + '</div></div>';
//     }

//     function renderCalendar() {
//         const p = cfg.today.split('-').map(Number);
//         const a = new Date(Date.UTC(p[0], p[1] - 1 + calOffset, 1));
//         const b = new Date(Date.UTC(p[0], p[1] + calOffset, 1));
//         calendarGrid.innerHTML = buildMonth(a.getUTCFullYear(), a.getUTCMonth()) + buildMonth(b.getUTCFullYear(), b.getUTCMonth());
//         $('cal-prev').disabled = calOffset === 0;
//         $('cal-next').disabled = calOffset >= 11;
//         refreshDateDisplays();
//     }

//     function refreshDateDisplays() {
//         checkinInput.value = selectedCheckin ? formatDisplay(selectedCheckin) : 'Select date';
//         checkinInput.dataset.date = selectedCheckin || '';
//         checkoutInput.value = selectedCheckout ? formatDisplay(selectedCheckout) : 'Select date';
//         checkoutInput.dataset.date = selectedCheckout || '';
//         $('cal-checkin-label').textContent = checkinInput.value;
//         $('cal-checkout-label').textContent = checkoutInput.value;
//         calendarGrid.querySelectorAll('.date-cell[data-date]').forEach((cell) => {
//             const dt = cell.dataset.date;
//             cell.classList.toggle('selected', dt === selectedCheckin || dt === selectedCheckout);
//             cell.classList.toggle('in-range', !!(selectedCheckin && selectedCheckout && dt > selectedCheckin && dt < selectedCheckout));
//         });
//     }

//     calendarGrid.addEventListener('click', function (e) {
//         const cell = e.target.closest('.date-cell');
//         if (!cell || cell.classList.contains('disabled') || !cell.dataset.date) return;
//         const clicked = cell.dataset.date;
//         if (!pickingCheckout || clicked <= selectedCheckin) {
//             selectedCheckin = clicked;
//             selectedCheckout = null;
//             pickingCheckout = true;
//             refreshDateDisplays();
//         } else {
//             selectedCheckout = clicked;
//             pickingCheckout = false;
//             refreshDateDisplays();
//             calendarPopup.classList.remove('active');
//             onDatesChanged();
//         }
//     });

//     $('cal-prev').addEventListener('click', () => { if (calOffset > 0) { calOffset--; renderCalendar(); } });
//     $('cal-next').addEventListener('click', () => { if (calOffset < 11) { calOffset++; renderCalendar(); } });

//     function toggleCalendar(e) { e.stopPropagation(); calendarPopup.classList.toggle('active'); }
//     $('checkin-group').addEventListener('click', toggleCalendar);
//     $('checkout-group').addEventListener('click', toggleCalendar);
//     document.addEventListener('click', function (e) {
//         if (!calendarPopup.contains(e.target) && !$('checkin-group').contains(e.target) && !$('checkout-group').contains(e.target)) {
//             calendarPopup.classList.remove('active');
//         }
//     });

//     $('btn-search').addEventListener('click', function () {
//         if (!currentDates()) { alert('Please select check-in and check-out dates.'); return; }
//         calendarPopup.classList.remove('active');
//         onDatesChanged();
//         const btn = this;
//         btn.textContent = '✓ UPDATED';
//         btn.style.backgroundColor = '#38a169';
//         setTimeout(() => { btn.textContent = 'SEARCH'; btn.style.backgroundColor = '#ff9800'; }, 1500);
//     });

//     // ================= room detail modal (content comes from the database) =================
//     const modal = $('room-details-modal');
//     const modalBody = $('modal-body-content');
//     const modalTabs = document.querySelectorAll('#room-details-modal .modal-tab');
//     let currentKey = null;

//     function renderTab(key, tab) {
//         const m = roomMeta[key] || {};
//         let html = '';
//         if (tab === 'images') {
//             html = (m.images && m.images.length)
//                 ? '<div class="gallery-grid">' + m.images.map((src) =>
//                     '<a href="' + escapeHtml(src) + '" target="_blank" rel="noopener"><img src="' + escapeHtml(src) + '" alt="Room image"></a>').join('') + '</div>'
//                 : '<div class="no-gallery-images"><i class="fas fa-images"></i><p>No images available for this room.</p></div>';
//         } else if (tab === 'details') {
//             html = '<div><strong>Property:</strong> ' + escapeHtml(m.property) + '<br>' +
//                 '<strong>Address:</strong> ' + escapeHtml(m.address) + '<br>' +
//                 (m.description ? '<strong>Room Description:</strong> ' + escapeHtml(m.description).replace(/\n/g, '<br>') : '') + '</div>';
//         } else if (tab === 'cancellation') {
//             html = '<div>' + escapeHtml(m.cancellation) + '</div>';
//         } else if (tab === 'tc') {
//             html = '<div>' + escapeHtml(m.times) + '. Government ID required at check-in.</div>';
//         } else if (tab === 'amenities') {
//             html = (m.amenities && m.amenities.length)
//                 ? '<ul>' + m.amenities.map((a) => '<li>' + escapeHtml(a) + '</li>').join('') + '</ul>'
//                 : '<div>No amenities listed.</div>';
//         } else if (tab === 'bedtypes') {
//             html = '<ul><li>' + escapeHtml(m.bed) + '</li></ul>';
//         }
//         modalBody.innerHTML = html;
//     }

//     function openModal(key, tab) {
//         currentKey = key;
//         const m = roomMeta[key] || {};
//         $('modal-title').textContent = (m.title || 'Room Details') + (m.property ? ' - ' + m.property : '');
//         modalTabs.forEach((t) => t.classList.toggle('active', t.dataset.tab === tab));
//         renderTab(key, tab);
//         modal.classList.add('active');
//         document.body.style.overflow = 'hidden';
//     }

//     function closeModal() { modal.classList.remove('active'); document.body.style.overflow = ''; }

//     cards.forEach((card) => {
//         card.querySelector('.more-link').addEventListener('click', (e) => { e.preventDefault(); openModal(card.dataset.key, 'images'); });
//         card.querySelector('.room-amenities-link').addEventListener('click', (e) => { e.preventDefault(); openModal(card.dataset.key, 'amenities'); });
//     });
//     modalTabs.forEach((tab) => tab.addEventListener('click', function () {
//         modalTabs.forEach((t) => t.classList.remove('active'));
//         this.classList.add('active');
//         renderTab(currentKey, this.dataset.tab);
//     }));
//     $('modal-close').addEventListener('click', closeModal);
//     modal.addEventListener('click', function (e) { if (e.target === this) closeModal(); });
//     document.addEventListener('keydown', function (e) {
//         if (e.key === 'Escape') { closeModal(); closeMonthlyModal(); }
//     });

//     // ================= monthly stay =================
//     const monthlyModal = $('monthly-modal');
//     const monthlyMonths = $('monthly-months');
//     let monthlyAfter = null;

//     function updateMonthlyPreview() {
//         const ci = selectedCheckin;
//         if (!ci) return;
//         const co = addMonths(ci, parseInt(monthlyMonths.value, 10) || 1);
//         $('monthly-prev-in').textContent = formatDisplay(ci);
//         $('monthly-prev-out').textContent = formatDisplay(co);
//         $('monthly-prev-nights').textContent = daysBetween(ci, co);
//     }

//     function openMonthlyModal(card, after) {
//         monthlyAfter = after || null;
//         $('monthly-msg').innerHTML = '<strong>' + escapeHtml(card.dataset.title || 'This room') + '</strong> is a <strong>monthly stay</strong> room. ' +
//             'It can only be booked for whole months (1 month, 2 months, ...), not for a few days. Choose how many months you would like to stay.';
//         const cur = wholeMonths(selectedCheckin, selectedCheckout);
//         monthlyMonths.value = (cur >= 1 && cur <= 12) ? String(cur) : '1';
//         updateMonthlyPreview();
//         monthlyModal.classList.add('active');
//         document.body.style.overflow = 'hidden';
//     }

//     function closeMonthlyModal() {
//         monthlyModal.classList.remove('active');
//         document.body.style.overflow = '';
//         monthlyAfter = null;
//     }

//     monthlyMonths.addEventListener('change', updateMonthlyPreview);
//     $('monthly-close').addEventListener('click', closeMonthlyModal);
//     $('monthly-cancel').addEventListener('click', closeMonthlyModal);
//     monthlyModal.addEventListener('click', function (e) { if (e.target === this) closeMonthlyModal(); });

//     $('monthly-continue').addEventListener('click', function () {
//         if (!selectedCheckin) { closeMonthlyModal(); return; }
//         const cb = monthlyAfter;
//         selectedCheckout = addMonths(selectedCheckin, parseInt(monthlyMonths.value, 10) || 1);
//         pickingCheckout = false;
//         refreshDateDisplays();
//         closeMonthlyModal();
//         if (cb) cb();
//         onDatesChanged();
//     });

//     // UI convenience only. The server enforces the whole-month rule on every quote and hold.
//     function monthlyDatesOk() {
//         for (const key of selectedKeys()) {
//             const card = cards.find((c) => c.dataset.key === key);
//             if (card && card.dataset.monthly === '1' && !wholeMonths(selectedCheckin, selectedCheckout)) {
//                 openMonthlyModal(card, null);
//                 return false;
//             }
//         }
//         return true;
//     }

//     // ================= add / remove rooms =================
//     function addToCart(btn) { btn.classList.add('added'); btn.textContent = 'REMOVE'; updateQuote(); }

//     cards.forEach((card) => {
//         const btn = card.querySelector('.btn-toggle-room');
//         btn.addEventListener('click', function () {
//             if (btn.disabled) return;
//             if (btn.classList.contains('added')) {
//                 btn.classList.remove('added');
//                 btn.textContent = 'ADD';
//                 updateQuote();
//                 return;
//             }
//             if (card.dataset.monthly === '1') { openMonthlyModal(card, () => addToCart(btn)); return; }
//             addToCart(btn);
//         });
//     });

//     // ================= steps =================
//     function showStep(n) {
//         inGuestView = n === 2;
//         $('room-selection-view').style.display = n === 1 ? 'block' : 'none';
//         $('guest-details-view').style.display = n === 2 ? 'block' : 'none';
//         $('terms-container').style.display = n === 2 ? 'block' : 'none';
//         $('step-2').classList.toggle('active', n === 2);
//         btnMain.textContent = n === 2 ? 'RESERVE ROOMS' : 'PROCEED';
//         $('center-content').scrollTop = 0;
//     }
//     $('step-1').style.cursor = 'pointer';
//     $('step-1').addEventListener('click', () => { if (!submitting) showStep(1); });

//     btnMain.addEventListener('click', function () {
//         if (submitting) return;
//         if (!selectedKeys().length) { alert('Please select at least one room to proceed.'); return; }
//         if (!currentDates()) { alert('Please select check-in and check-out dates.'); return; }
//         if (!monthlyDatesOk()) return;
//         if (!quote) { alert('The price could not be calculated. See the message under the summary.'); return; }
//         if (!inGuestView) { showStep(2); return; }
//         submitHold();
//     });

//     // ================= guest form =================
//     const firstName = $('first-name'), lastName = $('last-name'), email = $('email'), phone = $('phone');
//     const fieldMap = { first_name: 'field-firstname', last_name: 'field-lastname', email: 'field-email', phone: 'field-phone' };
//     const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

//     function showFormErrors(list) {
//         const box = $('validation-error'), ul = $('error-list');
//         ul.innerHTML = '';
//         list.forEach((t) => { const li = document.createElement('li'); li.textContent = t; ul.appendChild(li); });
//         box.style.display = list.length ? 'block' : 'none';
//     }

//     function validateGuestDetails() {
//         const errors = [];
//         document.querySelectorAll('.form-field').forEach((f) => f.classList.remove('has-error'));
//         const bad = (id, msg) => { errors.push(msg); $(id).classList.add('has-error'); };
//         if (!firstName.value.trim()) bad('field-firstname', 'First Name is required');
//         if (!lastName.value.trim()) bad('field-lastname', 'Last Name is required');
//         if (!EMAIL_RE.test(email.value.trim())) bad('field-email', 'Valid Email is required');
//         const digits = phone.value.replace(/\D/g, '');
//         if (digits.length < 10 || digits.length > 15) bad('field-phone', 'Valid Phone number is required (10-15 digits)');
//         showFormErrors(errors);
//         return errors.length === 0;
//     }

//     [firstName, lastName, phone].forEach((field) => {
//         field.addEventListener('blur', function () {
//             const parent = this.closest('.form-field');
//             if (parent) parent.classList.toggle('has-error', this.value.trim() === '');
//         });
//         field.addEventListener('input', function () {
//             const parent = this.closest('.form-field');
//             if (parent && this.value.trim() !== '') parent.classList.remove('has-error');
//             $('validation-error').style.display = 'none';
//         });
//     });

//     // ================= email verification (active only when the server requires it) =================
//     let emailVerified = false;
//     let verifiedForEmail = null;
//     let resendInterval = null;

//     function setOtpStatus(msg, isError) {
//         const el = $('otp-status');
//         if (!el) return;
//         el.textContent = msg;
//         el.className = 'otp-status ' + (isError ? 'error' : 'success');
//     }

//     if (cfg.otpRequired && $('btn-send-otp')) {
//         const startCooldown = () => {
//             let left = 60;
//             const resend = $('btn-resend-otp');
//             resend.disabled = true;
//             $('resend-timer').textContent = left;
//             clearInterval(resendInterval);
//             resendInterval = setInterval(() => {
//                 left--;
//                 $('resend-timer').textContent = left;
//                 if (left <= 0) { clearInterval(resendInterval); resend.disabled = false; resend.textContent = 'Resend Code'; }
//             }, 1000);
//         };

//         const sendOtp = () => {
//             const em = email.value.trim();
//             if (!EMAIL_RE.test(em)) { $('field-email').classList.add('has-error'); setOtpStatus('Enter a valid email first.', true); return; }
//             $('btn-send-otp').disabled = true;
//             request('POST', cfg.urls.sendOtp, { email: em }).then((res) => {
//                 $('btn-send-otp').disabled = false;
//                 if (res.ok) {
//                     $('otp-request-row').style.display = 'none';
//                     $('otp-verify-row').style.display = 'flex';
//                     setOtpStatus(res.data.message || 'Verification code sent.', false);
//                     startCooldown();
//                 } else { setOtpStatus(errorText(res), true); }
//             }).catch(() => { $('btn-send-otp').disabled = false; setOtpStatus('Could not send code. Try again.', true); });
//         };

//         $('btn-send-otp').addEventListener('click', sendOtp);
//         $('btn-resend-otp').addEventListener('click', sendOtp);

//         $('btn-verify-otp').addEventListener('click', function () {
//             const em = email.value.trim(), code = $('otp-input').value.trim();
//             if (!code) { setOtpStatus('Enter the code sent to your email.', true); return; }
//             this.disabled = true;
//             request('POST', cfg.urls.verifyOtp, { email: em, otp: code }).then((res) => {
//                 this.disabled = false;
//                 if (res.ok) {
//                     emailVerified = true; verifiedForEmail = em;
//                     $('otp-verify-row').style.display = 'none';
//                     $('verified-badge').style.display = 'flex';
//                     setOtpStatus('', false);
//                 } else { setOtpStatus(errorText(res), true); }
//             }).catch(() => { this.disabled = false; setOtpStatus('Verification failed. Try again.', true); });
//         });

//         email.addEventListener('input', function () {
//             if (verifiedForEmail && verifiedForEmail !== this.value.trim()) {
//                 emailVerified = false; verifiedForEmail = null;
//                 $('verified-badge').style.display = 'none';
//                 $('otp-request-row').style.display = 'flex';
//                 $('otp-verify-row').style.display = 'none';
//                 setOtpStatus('Email changed. Please verify again.', true);
//             }
//         });
//     }

//     // ================= reserve (create the 30-minute hold) =================
//     // Step 5e will start Razorpay from onHoldCreated(); until then the guest goes to the confirmation page.
//     function onHoldCreated(hold) {
//         $('step-3').classList.add('active');
//         window.location.href = cfg.urls.success + '?ref=' + enc(hold.group_ref);
//     }

//     function setSubmitting(on) {
//         submitting = on;
//         btnMain.disabled = on;
//         btnMain.textContent = on ? 'Reserving...' : 'RESERVE ROOMS';
//     }

//     function submitHold() {
//         const dates = currentDates();
//         if (!dates || !quote) return;
//         if (!validateGuestDetails()) return;
//         if (cfg.otpRequired && !(emailVerified && verifiedForEmail === email.value.trim())) {
//             setOtpStatus('Please verify your email before reserving.', true);
//             return;
//         }
//         if (!$('agree-terms').checked) { alert('Please agree to the Terms & Conditions.'); return; }

//         setSubmitting(true);                                  // blocks double-clicks
//         const body = Object.assign({
//             items: selectedKeys().map((k) => ({ key: k, quantity: 1 })),
//             first_name: firstName.value.trim(),
//             last_name: lastName.value.trim(),
//             email: email.value.trim(),
//             phone: phone.value.trim(),
//             special_request: $('special-request').value.trim()
//         }, dates);

//         request('POST', cfg.urls.hold, body).then((res) => {
//             if (res.status === 201) { onHoldCreated(res.data); return; }
//             setSubmitting(false);
//             if (res.status === 409) {
//                 alert(errorText(res));
//                 showStep(1);
//                 refreshAvailability();
//             } else if (res.status === 400 && res.data && typeof res.data === 'object') {
//                 Object.keys(fieldMap).forEach((f) => { if (res.data[f]) $(fieldMap[f]).classList.add('has-error'); });
//                 showFormErrors([errorText(res)]);
//             } else if (res.data && res.data.error && res.data.error.code === 'email_not_verified') {
//                 setOtpStatus(res.data.error.message, true);
//             } else {
//                 alert(errorText(res));
//             }
//         }).catch(() => { setSubmitting(false); alert('Could not reach the server. Please try again.'); });
//     }

//     // ================= init =================
//     renderCalendar();
//     renderSummary();
// });

document.addEventListener('DOMContentLoaded', function () {
    'use strict';

    const cfg = window.BOOKING_CONFIG;
    const roomMeta = JSON.parse(document.getElementById('room-data').textContent);
    const $ = (id) => document.getElementById(id);
    const enc = encodeURIComponent;

    // ================= helpers =================
    function escapeHtml(str) {
        return String(str == null ? '' : str).replace(/[&<>"']/g, (c) =>
            ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    function money(v) {
        return '₹ ' + Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function ordinal(day) {
        return (day % 10 === 1 && day !== 11) ? 'st' : (day % 10 === 2 && day !== 12) ? 'nd' : (day % 10 === 3 && day !== 13) ? 'rd' : 'th';
    }

    function formatSummaryDate(ds) {
        const d = new Date(ds + 'T00:00:00');
        return d.getDate() + ordinal(d.getDate()) + ' ' + d.toLocaleDateString('en-GB', { month: 'short' }) + ' ' + d.getFullYear();
    }

    function formatDisplay(ds) {
        const d = new Date(ds + 'T00:00:00');
        return String(d.getDate()).padStart(2, '0') + ' ' + d.toLocaleDateString('en-GB', { month: 'short' }) + ' ' +
            d.getFullYear() + ', ' + d.toLocaleDateString('en-GB', { weekday: 'short' });
    }

    function daysBetween(a, b) {
        return Math.round((new Date(b + 'T00:00:00') - new Date(a + 'T00:00:00')) / 86400000);
    }

    // 31 Jan + 1 month = end of Feb (same rule as the server's add_months)
    function addMonths(ds, m) {
        const p = ds.split('-').map(Number);
        const t = new Date(Date.UTC(p[0], p[1] - 1 + m, 1));
        const last = new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth() + 1, 0)).getUTCDate();
        t.setUTCDate(Math.min(p[2], last));
        return t.toISOString().slice(0, 10);
    }

    function wholeMonths(ci, co) {
        if (!ci || !co) return 0;
        for (let m = 1; m <= 24; m++) { if (addMonths(ci, m) === co) return m; }
        return 0;
    }

    function request(method, url, payload) {
        const opts = { method: method, headers: { 'Accept': 'application/json' }, credentials: 'same-origin' };
        if (method !== 'GET') {
            opts.headers['Content-Type'] = 'application/json';
            opts.headers['X-CSRFToken'] = cfg.csrf;
            opts.body = JSON.stringify(payload || {});
        }
        return fetch(url, opts).then((r) =>
            r.json().catch(() => ({})).then((data) => ({ ok: r.ok, status: r.status, data: data })));
    }

    // Flatten any API error body (custom {"error"} or DRF field errors) to one string.
    function errorText(res) {
        const d = res.data || {};
        if (d.error && d.error.message) return d.error.message;
        if (res.status === 429) return 'Too many requests. Please wait a moment and try again.';
        const parts = [];
        (function walk(v) {
            if (typeof v === 'string') parts.push(v);
            else if (Array.isArray(v)) v.forEach(walk);
            else if (v && typeof v === 'object') Object.values(v).forEach(walk);
        })(d);
        return parts.length ? parts.join(' ') : 'Something went wrong. Please try again.';
    }

    // ================= state =================
    const checkinInput = $('checkin-input');
    const checkoutInput = $('checkout-input');
    let selectedCheckin = checkinInput.dataset.date;
    let selectedCheckout = checkoutInput.dataset.date;
    let pickingCheckout = false;
    let calOffset = 0;
    let quote = null;            // last good server quote for the current cart
    let inGuestView = false;
    let submitting = false;
    let heldGroup = null;        // set once a hold exists; the button then retries payment
    let availSeq = 0;
    let quoteSeq = 0;

    const cards = Array.from(document.querySelectorAll('.room-card'));
    const btnMain = $('btn-main-action');

    function currentDates() {
        if (!selectedCheckin || !selectedCheckout || selectedCheckout <= selectedCheckin) return null;
        return { check_in: selectedCheckin, check_out: selectedCheckout };
    }

    function selectedKeys() {
        return cards.filter((c) => c.querySelector('.btn-toggle-room').classList.contains('added'))
            .map((c) => c.dataset.key);
    }

    // ================= summary =================
    function showSummaryError(msg) {
        const el = $('summary-error');
        el.textContent = msg;
        el.style.display = msg ? 'block' : 'none';
    }

    function renderSummary() {
        const dates = currentDates();
        $('summary-rooms').textContent = quote ? quote.count : 0;
        $('summary-guests').textContent = quote ? quote.guests : 0;
        $('summary-nights').textContent = quote ? quote.nights : (dates ? daysBetween(dates.check_in, dates.check_out) : 1);
        $('summary-total').textContent = money(quote ? quote.total : 0);
        $('room-guest-select').options[0].textContent = quote
            ? quote.count + ' Room' + (quote.count > 1 ? 's' : '') + ', ' + quote.guests + ' Adult' + (quote.guests > 1 ? 's' : '') + ', 0 Children'
            : '0 Room, 0 Adult, 0 Children';
    }

    function updateSummaryDates() {
        $('summary-checkin').textContent = selectedCheckin ? formatSummaryDate(selectedCheckin) : '-';
        $('summary-checkout').textContent = selectedCheckout ? formatSummaryDate(selectedCheckout) : '-';
    }

    // The server is the only source of prices. On failure we show the message and no total.
    function updateQuote() {
        const keys = selectedKeys();
        const dates = currentDates();
        if (!keys.length) { quote = null; showSummaryError(''); renderSummary(); return Promise.resolve(); }
        if (!dates) { quote = null; showSummaryError('Select your check-in and check-out dates.'); renderSummary(); return Promise.resolve(); }

        const seq = ++quoteSeq;
        const body = Object.assign({ items: keys.map((k) => ({ key: k, quantity: 1 })) }, dates);
        return request('POST', cfg.urls.quote, body).then((res) => {
            if (seq !== quoteSeq) return;                 // a newer request superseded this one
            if (!res.ok) { quote = null; showSummaryError(errorText(res)); }
            else { quote = res.data; showSummaryError(''); }
            renderSummary();
        }).catch(() => {
            if (seq !== quoteSeq) return;
            quote = null;
            showSummaryError('Could not reach the server. Please try again.');
            renderSummary();
        });
    }

    // ================= availability =================
    function refreshAvailability() {
        const dates = currentDates();
        if (!dates) { return updateQuote(); }
        const seq = ++availSeq;
        const url = cfg.urls.availability + '?check_in=' + enc(dates.check_in) + '&check_out=' + enc(dates.check_out);

        return request('GET', url).then((res) => {
            if (seq !== availSeq) return;
            if (!res.ok) { showSummaryError(errorText(res)); return; }

            const byKey = {};
            res.data.properties.forEach((p) => p.room_types.forEach((rt) => { byKey[rt.key] = rt; }));
            const removed = [];

            cards.forEach((card) => {
                const rt = byKey[card.dataset.key];
                const units = rt ? rt.available_count : 0;
                const btn = card.querySelector('.btn-toggle-room');
                const note = card.querySelector('[data-avail-note]');
                const hold = card.querySelector('[data-holding]');
                card.querySelector('[data-units]').textContent = 'Units Available : ' + units;

                if (units < 1) {
                    if (btn.classList.contains('added')) { btn.classList.remove('added'); removed.push(card.dataset.title); }
                    card.classList.add('sold-out');
                    btn.disabled = true;
                    btn.textContent = 'SOLD OUT';
                    note.textContent = 'No units available for these dates';
                    note.className = 'availability-note none';
                } else {
                    card.classList.remove('sold-out');
                    if (!btn.classList.contains('added')) { btn.disabled = false; btn.textContent = 'ADD'; }
                    if (units <= 2) {
                        note.textContent = 'Only ' + units + ' unit(s) left for these dates';
                        note.className = 'availability-note low';
                    } else {
                        note.textContent = '';
                        note.className = 'availability-note';
                    }
                }

                const holding = rt ? rt.holding_count : 0;       // real number of unexpired holds
                if (hold) {
                    hold.hidden = !holding;
                    hold.textContent = holding ? holding + (holding === 1 ? ' person is' : ' people are') + ' booking now' : '';
                }
            });

            if (removed.length) {
                alert('No longer available for these dates and removed from your selection: ' + removed.join(', '));
            }
            return updateQuote();
        }).catch(() => {});
    }

    function onDatesChanged() {
        updateSummaryDates();
        refreshAvailability();
    }

    // ================= calendar =================
    const calendarPopup = $('calendar-popup');
    const calendarGrid = $('calendar-grid-container');

    function buildMonth(y, m) {                           // m is 0-based
        const first = new Date(Date.UTC(y, m, 1));
        const offset = (first.getUTCDay() + 6) % 7;       // Monday first
        const days = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
        const title = first.toLocaleDateString('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' });
        let h = '<div class="month-col"><div class="month-title">' + title + '</div>' +
            '<div class="days-header"><span>Mo</span><span>Tu</span><span>We</span><span>Th</span><span>Fr</span><span>Sa</span><span>Su</span></div>' +
            '<div class="days-grid">';
        for (let i = 0; i < offset; i++) h += '<div class="date-cell disabled"></div>';
        for (let d = 1; d <= days; d++) {
            const ds = y + '-' + String(m + 1).padStart(2, '0') + '-' + String(d).padStart(2, '0');
            h += '<div class="date-cell' + (ds < cfg.today ? ' disabled' : '') + '" data-date="' + ds + '">' + d + '<span class="price-sub"></span></div>';
        }
        return h + '</div></div>';
    }

    function renderCalendar() {
        const p = cfg.today.split('-').map(Number);
        const a = new Date(Date.UTC(p[0], p[1] - 1 + calOffset, 1));
        const b = new Date(Date.UTC(p[0], p[1] + calOffset, 1));
        calendarGrid.innerHTML = buildMonth(a.getUTCFullYear(), a.getUTCMonth()) + buildMonth(b.getUTCFullYear(), b.getUTCMonth());
        $('cal-prev').disabled = calOffset === 0;
        $('cal-next').disabled = calOffset >= 11;
        refreshDateDisplays();
    }

    function refreshDateDisplays() {
        checkinInput.value = selectedCheckin ? formatDisplay(selectedCheckin) : 'Select date';
        checkinInput.dataset.date = selectedCheckin || '';
        checkoutInput.value = selectedCheckout ? formatDisplay(selectedCheckout) : 'Select date';
        checkoutInput.dataset.date = selectedCheckout || '';
        $('cal-checkin-label').textContent = checkinInput.value;
        $('cal-checkout-label').textContent = checkoutInput.value;
        calendarGrid.querySelectorAll('.date-cell[data-date]').forEach((cell) => {
            const dt = cell.dataset.date;
            cell.classList.toggle('selected', dt === selectedCheckin || dt === selectedCheckout);
            cell.classList.toggle('in-range', !!(selectedCheckin && selectedCheckout && dt > selectedCheckin && dt < selectedCheckout));
        });
    }

    calendarGrid.addEventListener('click', function (e) {
        const cell = e.target.closest('.date-cell');
        if (!cell || cell.classList.contains('disabled') || !cell.dataset.date) return;
        const clicked = cell.dataset.date;
        if (!pickingCheckout || clicked <= selectedCheckin) {
            selectedCheckin = clicked;
            selectedCheckout = null;
            pickingCheckout = true;
            refreshDateDisplays();
        } else {
            selectedCheckout = clicked;
            pickingCheckout = false;
            refreshDateDisplays();
            calendarPopup.classList.remove('active');
            onDatesChanged();
        }
    });

    $('cal-prev').addEventListener('click', () => { if (calOffset > 0) { calOffset--; renderCalendar(); } });
    $('cal-next').addEventListener('click', () => { if (calOffset < 11) { calOffset++; renderCalendar(); } });

    function toggleCalendar(e) { e.stopPropagation(); calendarPopup.classList.toggle('active'); }
    $('checkin-group').addEventListener('click', toggleCalendar);
    $('checkout-group').addEventListener('click', toggleCalendar);
    document.addEventListener('click', function (e) {
        if (!calendarPopup.contains(e.target) && !$('checkin-group').contains(e.target) && !$('checkout-group').contains(e.target)) {
            calendarPopup.classList.remove('active');
        }
    });

    $('btn-search').addEventListener('click', function () {
        if (!currentDates()) { alert('Please select check-in and check-out dates.'); return; }
        calendarPopup.classList.remove('active');
        onDatesChanged();
        const btn = this;
        btn.textContent = '✓ UPDATED';
        btn.style.backgroundColor = '#38a169';
        setTimeout(() => { btn.textContent = 'SEARCH'; btn.style.backgroundColor = '#ff9800'; }, 1500);
    });

    // ================= room detail modal (content comes from the database) =================
    const modal = $('room-details-modal');
    const modalBody = $('modal-body-content');
    const modalTabs = document.querySelectorAll('#room-details-modal .modal-tab');
    let currentKey = null;

    function renderTab(key, tab) {
        const m = roomMeta[key] || {};
        let html = '';
        if (tab === 'images') {
            html = (m.images && m.images.length)
                ? '<div class="gallery-grid">' + m.images.map((src) =>
                    '<a href="' + escapeHtml(src) + '" target="_blank" rel="noopener"><img src="' + escapeHtml(src) + '" alt="Room image"></a>').join('') + '</div>'
                : '<div class="no-gallery-images"><i class="fas fa-images"></i><p>No images available for this room.</p></div>';
        } else if (tab === 'details') {
            html = '<div><strong>Property:</strong> ' + escapeHtml(m.property) + '<br>' +
                '<strong>Address:</strong> ' + escapeHtml(m.address) + '<br>' +
                (m.description ? '<strong>Room Description:</strong> ' + escapeHtml(m.description).replace(/\n/g, '<br>') : '') + '</div>';
        } else if (tab === 'cancellation') {
            html = '<div>' + escapeHtml(m.cancellation) + '</div>';
        } else if (tab === 'tc') {
            html = '<div>' + escapeHtml(m.times) + '. Government ID required at check-in.</div>';
        } else if (tab === 'amenities') {
            html = (m.amenities && m.amenities.length)
                ? '<ul>' + m.amenities.map((a) => '<li>' + escapeHtml(a) + '</li>').join('') + '</ul>'
                : '<div>No amenities listed.</div>';
        } else if (tab === 'bedtypes') {
            html = '<ul><li>' + escapeHtml(m.bed) + '</li></ul>';
        }
        modalBody.innerHTML = html;
    }

    function openModal(key, tab) {
        currentKey = key;
        const m = roomMeta[key] || {};
        $('modal-title').textContent = (m.title || 'Room Details') + (m.property ? ' - ' + m.property : '');
        modalTabs.forEach((t) => t.classList.toggle('active', t.dataset.tab === tab));
        renderTab(key, tab);
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    function closeModal() { modal.classList.remove('active'); document.body.style.overflow = ''; }

    cards.forEach((card) => {
        card.querySelector('.more-link').addEventListener('click', (e) => { e.preventDefault(); openModal(card.dataset.key, 'images'); });
        card.querySelector('.room-amenities-link').addEventListener('click', (e) => { e.preventDefault(); openModal(card.dataset.key, 'amenities'); });
    });
    modalTabs.forEach((tab) => tab.addEventListener('click', function () {
        modalTabs.forEach((t) => t.classList.remove('active'));
        this.classList.add('active');
        renderTab(currentKey, this.dataset.tab);
    }));
    $('modal-close').addEventListener('click', closeModal);
    modal.addEventListener('click', function (e) { if (e.target === this) closeModal(); });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { closeModal(); closeMonthlyModal(); }
    });

    // ================= monthly stay =================
    const monthlyModal = $('monthly-modal');
    const monthlyMonths = $('monthly-months');
    let monthlyAfter = null;

    function updateMonthlyPreview() {
        const ci = selectedCheckin;
        if (!ci) return;
        const co = addMonths(ci, parseInt(monthlyMonths.value, 10) || 1);
        $('monthly-prev-in').textContent = formatDisplay(ci);
        $('monthly-prev-out').textContent = formatDisplay(co);
        $('monthly-prev-nights').textContent = daysBetween(ci, co);
    }

    function openMonthlyModal(card, after) {
        monthlyAfter = after || null;
        $('monthly-msg').innerHTML = '<strong>' + escapeHtml(card.dataset.title || 'This room') + '</strong> is a <strong>monthly stay</strong> room. ' +
            'It can only be booked for whole months (1 month, 2 months, ...), not for a few days. Choose how many months you would like to stay.';
        const cur = wholeMonths(selectedCheckin, selectedCheckout);
        monthlyMonths.value = (cur >= 1 && cur <= 12) ? String(cur) : '1';
        updateMonthlyPreview();
        monthlyModal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    function closeMonthlyModal() {
        monthlyModal.classList.remove('active');
        document.body.style.overflow = '';
        monthlyAfter = null;
    }

    monthlyMonths.addEventListener('change', updateMonthlyPreview);
    $('monthly-close').addEventListener('click', closeMonthlyModal);
    $('monthly-cancel').addEventListener('click', closeMonthlyModal);
    monthlyModal.addEventListener('click', function (e) { if (e.target === this) closeMonthlyModal(); });

    $('monthly-continue').addEventListener('click', function () {
        if (!selectedCheckin) { closeMonthlyModal(); return; }
        const cb = monthlyAfter;
        selectedCheckout = addMonths(selectedCheckin, parseInt(monthlyMonths.value, 10) || 1);
        pickingCheckout = false;
        refreshDateDisplays();
        closeMonthlyModal();
        if (cb) cb();
        onDatesChanged();
    });

    // UI convenience only. The server enforces the whole-month rule on every quote and hold.
    function monthlyDatesOk() {
        for (const key of selectedKeys()) {
            const card = cards.find((c) => c.dataset.key === key);
            if (card && card.dataset.monthly === '1' && !wholeMonths(selectedCheckin, selectedCheckout)) {
                openMonthlyModal(card, null);
                return false;
            }
        }
        return true;
    }

    // ================= add / remove rooms =================
    function addToCart(btn) { btn.classList.add('added'); btn.textContent = 'REMOVE'; updateQuote(); }

    cards.forEach((card) => {
        const btn = card.querySelector('.btn-toggle-room');
        btn.addEventListener('click', function () {
            if (btn.disabled) return;
            if (btn.classList.contains('added')) {
                btn.classList.remove('added');
                btn.textContent = 'ADD';
                updateQuote();
                return;
            }
            if (card.dataset.monthly === '1') { openMonthlyModal(card, () => addToCart(btn)); return; }
            addToCart(btn);
        });
    });

    // ================= steps =================
    function payLabel() { return heldGroup ? 'PAY NOW' : (inGuestView ? 'RESERVE ROOMS' : 'PROCEED'); }

    function showStep(n) {
        inGuestView = n === 2;
        $('room-selection-view').style.display = n === 1 ? 'block' : 'none';
        $('guest-details-view').style.display = n === 2 ? 'block' : 'none';
        $('terms-container').style.display = n === 2 ? 'block' : 'none';
        $('step-2').classList.toggle('active', n === 2);
        btnMain.textContent = payLabel();
        $('center-content').scrollTop = 0;
    }
    $('step-1').style.cursor = 'pointer';
    $('step-1').addEventListener('click', () => { if (!submitting && !heldGroup) showStep(1); });

    btnMain.addEventListener('click', function () {
        if (submitting) return;
        if (heldGroup) { startPayment(heldGroup); return; }
        if (!selectedKeys().length) { alert('Please select at least one room to proceed.'); return; }
        if (!currentDates()) { alert('Please select check-in and check-out dates.'); return; }
        if (!monthlyDatesOk()) return;
        if (!quote) { alert('The price could not be calculated. See the message under the summary.'); return; }
        if (!inGuestView) { showStep(2); return; }
        submitHold();
    });

    // ================= guest form =================
    const firstName = $('first-name'), lastName = $('last-name'), email = $('email'), phone = $('phone');
    const fieldMap = { first_name: 'field-firstname', last_name: 'field-lastname', email: 'field-email', phone: 'field-phone' };
    const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    function showFormErrors(list) {
        const box = $('validation-error'), ul = $('error-list');
        ul.innerHTML = '';
        list.forEach((t) => { const li = document.createElement('li'); li.textContent = t; ul.appendChild(li); });
        box.style.display = list.length ? 'block' : 'none';
    }

    function validateGuestDetails() {
        const errors = [];
        document.querySelectorAll('.form-field').forEach((f) => f.classList.remove('has-error'));
        const bad = (id, msg) => { errors.push(msg); $(id).classList.add('has-error'); };
        if (!firstName.value.trim()) bad('field-firstname', 'First Name is required');
        if (!lastName.value.trim()) bad('field-lastname', 'Last Name is required');
        if (!EMAIL_RE.test(email.value.trim())) bad('field-email', 'Valid Email is required');
        const digits = phone.value.replace(/\D/g, '');
        if (digits.length < 10 || digits.length > 15) bad('field-phone', 'Valid Phone number is required (10-15 digits)');
        showFormErrors(errors);
        return errors.length === 0;
    }

    [firstName, lastName, phone].forEach((field) => {
        field.addEventListener('blur', function () {
            const parent = this.closest('.form-field');
            if (parent) parent.classList.toggle('has-error', this.value.trim() === '');
        });
        field.addEventListener('input', function () {
            const parent = this.closest('.form-field');
            if (parent && this.value.trim() !== '') parent.classList.remove('has-error');
            $('validation-error').style.display = 'none';
        });
    });

    // ================= email verification (active only when the server requires it) =================
    let emailVerified = false;
    let verifiedForEmail = null;
    let resendInterval = null;

    function setOtpStatus(msg, isError) {
        const el = $('otp-status');
        if (!el) return;
        el.textContent = msg;
        el.className = 'otp-status ' + (isError ? 'error' : 'success');
    }

    if (cfg.otpRequired && $('btn-send-otp')) {
        const startCooldown = () => {
            let left = 60;
            const resend = $('btn-resend-otp');
            resend.disabled = true;
            $('resend-timer').textContent = left;
            clearInterval(resendInterval);
            resendInterval = setInterval(() => {
                left--;
                $('resend-timer').textContent = left;
                if (left <= 0) { clearInterval(resendInterval); resend.disabled = false; resend.textContent = 'Resend Code'; }
            }, 1000);
        };

        const sendOtp = () => {
            const em = email.value.trim();
            if (!EMAIL_RE.test(em)) { $('field-email').classList.add('has-error'); setOtpStatus('Enter a valid email first.', true); return; }
            $('btn-send-otp').disabled = true;
            request('POST', cfg.urls.sendOtp, { email: em }).then((res) => {
                $('btn-send-otp').disabled = false;
                if (res.ok) {
                    $('otp-request-row').style.display = 'none';
                    $('otp-verify-row').style.display = 'flex';
                    setOtpStatus(res.data.message || 'Verification code sent.', false);
                    startCooldown();
                } else { setOtpStatus(errorText(res), true); }
            }).catch(() => { $('btn-send-otp').disabled = false; setOtpStatus('Could not send code. Try again.', true); });
        };

        $('btn-send-otp').addEventListener('click', sendOtp);
        $('btn-resend-otp').addEventListener('click', sendOtp);

        $('btn-verify-otp').addEventListener('click', function () {
            const em = email.value.trim(), code = $('otp-input').value.trim();
            if (!code) { setOtpStatus('Enter the code sent to your email.', true); return; }
            this.disabled = true;
            request('POST', cfg.urls.verifyOtp, { email: em, otp: code }).then((res) => {
                this.disabled = false;
                if (res.ok) {
                    emailVerified = true; verifiedForEmail = em;
                    $('otp-verify-row').style.display = 'none';
                    $('verified-badge').style.display = 'flex';
                    setOtpStatus('', false);
                } else { setOtpStatus(errorText(res), true); }
            }).catch(() => { this.disabled = false; setOtpStatus('Verification failed. Try again.', true); });
        });

        email.addEventListener('input', function () {
            if (verifiedForEmail && verifiedForEmail !== this.value.trim()) {
                emailVerified = false; verifiedForEmail = null;
                $('verified-badge').style.display = 'none';
                $('otp-request-row').style.display = 'flex';
                $('otp-verify-row').style.display = 'none';
                setOtpStatus('Email changed. Please verify again.', true);
            }
        });
    }

    // ================= reserve, then pay =================
    function setSubmitting(on, text) {
        submitting = on;
        btnMain.disabled = on;
        btnMain.textContent = on ? (text || 'Please wait...') : payLabel();
    }

    // Hold created -> open payment. Closing the popup keeps the hold; PAY NOW retries.
    function onHoldCreated(hold) {
        heldGroup = hold.group_ref;
        $('step-1').style.cursor = 'default';
        startPayment(heldGroup);
    }

    function startPayment(groupRef) {
        setSubmitting(true, 'Starting payment...');
        request('POST', cfg.urls.createOrder, { group_ref: groupRef }).then((res) => {
            if (res.ok) { openCheckout(res.data); return; }
            setSubmitting(false);
            const code = res.data && res.data.error && res.data.error.code;
            if (code === 'already_paid') { window.location.href = cfg.urls.success + '?ref=' + enc(groupRef); return; }
            alert(errorText(res));
            if (code === 'hold_expired' || code === 'unknown_group') {
                heldGroup = null;
                $('step-1').style.cursor = 'pointer';
                showStep(1);
                refreshAvailability();
            }
        }).catch(() => { setSubmitting(false); alert('Could not reach the server. Please try again.'); });
    }

    function openCheckout(o) {
        if (typeof Razorpay === 'undefined') {
            setSubmitting(false);
            alert('The payment window could not load. Check your connection and try again.');
            return;
        }
        let paid = false;
        const rzp = new Razorpay({
            key: o.key, amount: o.amount, currency: o.currency, order_id: o.order_id,
            name: o.name, description: o.description,
            prefill: { name: (firstName.value + ' ' + lastName.value).trim(), email: email.value.trim(), contact: phone.value.trim() },
            theme: { color: '#ff9800' },
            handler: function (resp) { paid = true; confirmPayment(resp, o.group_ref); },
            modal: { ondismiss: function () { if (!paid) setSubmitting(false); } }
        });
        rzp.on('payment.failed', function (r) {
            alert('Payment failed: ' + ((r.error && r.error.description) || 'please try again.'));
        });
        setSubmitting(true, 'Complete the payment...');
        rzp.open();
    }

    // The browser only forwards Razorpay's signed proof. The server decides whether it is valid.
    function confirmPayment(resp, groupRef) {
        setSubmitting(true, 'Confirming payment...');
        request('POST', cfg.urls.verifyPayment, {
            razorpay_order_id: resp.razorpay_order_id,
            razorpay_payment_id: resp.razorpay_payment_id,
            razorpay_signature: resp.razorpay_signature
        }).then((res) => {
            if (!res.ok) alert(errorText(res));
            $('step-3').classList.add('active');
            window.location.href = cfg.urls.success + '?ref=' + enc((res.data && res.data.group_ref) || groupRef);
        }).catch(() => {
            window.location.href = cfg.urls.success + '?ref=' + enc(groupRef);
        });
    }

    function submitHold() {
        const dates = currentDates();
        if (!dates || !quote) return;
        if (!validateGuestDetails()) return;
        if (cfg.otpRequired && !(emailVerified && verifiedForEmail === email.value.trim())) {
            setOtpStatus('Please verify your email before reserving.', true);
            return;
        }
        if (!$('agree-terms').checked) { alert('Please agree to the Terms & Conditions.'); return; }

        setSubmitting(true, 'Reserving...');                  // blocks double-clicks
        const body = Object.assign({
            items: selectedKeys().map((k) => ({ key: k, quantity: 1 })),
            first_name: firstName.value.trim(),
            last_name: lastName.value.trim(),
            email: email.value.trim(),
            phone: phone.value.trim(),
            special_request: $('special-request').value.trim()
        }, dates);

        request('POST', cfg.urls.hold, body).then((res) => {
            if (res.status === 201) { onHoldCreated(res.data); return; }
            setSubmitting(false);
            if (res.status === 409) {
                alert(errorText(res));
                showStep(1);
                refreshAvailability();
            } else if (res.data && res.data.error && res.data.error.code === 'email_not_verified') {
                emailVerified = false; verifiedForEmail = null;
                $('verified-badge').style.display = 'none';
                $('otp-request-row').style.display = 'flex';
                $('otp-verify-row').style.display = 'none';
                setOtpStatus(res.data.error.message, true);
            } else if (res.status === 400 && res.data && typeof res.data === 'object') {
                Object.keys(fieldMap).forEach((f) => { if (res.data[f]) $(fieldMap[f]).classList.add('has-error'); });
                showFormErrors([errorText(res)]);
            } else {
                alert(errorText(res));
            }
        }).catch(() => { setSubmitting(false); alert('Could not reach the server. Please try again.'); });
    }

    // ================= init =================
    renderCalendar();
    renderSummary();
});