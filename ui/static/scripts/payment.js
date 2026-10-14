/*
  SOLFER PAYMENT PAGE
  ===================
  Flow:
    1. On load → GET /payment/initiate-payment
       Returns: { name, email, amount, currency, public_key, access_days }
       Populates customer row and price display.

    2. Card mode → FlutterwaveCheckout inline widget
       On success callback → GET /payment/status/<tx_ref> to confirm server-side.

    3. Transfer mode → POST /payment/transfer/generate
       Returns: { bank, account_number, account_name, amount, currency,
                  tx_ref, expires_at }
       Starts frontend polling loop → GET /payment/status/<tx_ref> every 8s.
       On confirmed → redirect to success page.
*/

var paymentData   = null;   // populated from /payment/initiate-payment
var txRef         = null;   // set when transfer is generated
var pollInterval  = null;   // setInterval handle
var POLL_EVERY_MS = 4000;   // 4 seconds
var MAX_POLLS     = 75;     // 10 minutes max (75 × 8s)
var pollCount     = 0;

/* ── Boot ── */
window.addEventListener('DOMContentLoaded', function () {
  loadPaymentContext();
  generateTransfer();  // Auto-start transfer flow for now (no card mode)
  switchMode('transfer'); // Show transfer tab by default
});

async function loadPaymentContext() {
  try {
    var res  = await fetch('/payment/initiate-payment', {
      method: "GET",
      headers: { 'X-CSRFToken': getCSRFToken() }
    });
    if (!res.ok) throw new Error('Server error');
    paymentData = await res.json();

    /* Customer row */
    var initials = paymentData.name
      .split(' ')
      .map(function(w){ return w[0]; })
      .slice(0, 2)
      .join('')
      .toUpperCase();

    document.getElementById('cust-avatar').textContent = initials;
    document.getElementById('cust-name').textContent   = paymentData.name;
    document.getElementById('cust-email').textContent  = paymentData.email;
    document.getElementById('cust-row').style.display  = 'flex';

    /* Price */
    document.getElementById('price-display').textContent =
      paymentData.currency + ' ' + Number(paymentData.amount).toLocaleString();

    /* Transfer amount label */
    document.getElementById('tf-amount').textContent =
      paymentData.currency + ' ' + Number(paymentData.amount).toLocaleString();

  } catch (e) {
    showAlert('Could not load payment details. Please refresh.', 'error');
  }
}

/* ── Mode switcher ── */
function switchMode(mode) {
  ['transfer'].forEach(function(m) {
    document.getElementById('tab-' + m).classList.toggle('active', m === mode);
    document.getElementById('panel-' + m).classList.toggle('active', m === mode);
  });
  clearAlert();
}


/* ── Transfer payment ── */
async function generateTransfer() {
  if (!paymentData) { showAlert('Payment details not loaded yet.', 'error'); return; }

  setBtnLoading('transfer-btn', 'transfer-btn-text', 'transfer-spinner', true);
  document.getElementById('transfer-btn').disabled = true;
  clearAlert();

  try {
    var res = await fetch('/payment/transfer/generate', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
      body:    JSON.stringify({ email: paymentData.email, name: paymentData.name })
    });
    var data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Generation failed');

    txRef = data.reference;
    console.log(data);
    /* Populate transfer box */
    document.getElementById('tf-bank').textContent  = data.account_bank_name;
    document.getElementById('tf-acct').textContent  = data.account_number;
    // document.getElementById('tf-name').textContent  = data.account_name;
    document.getElementById('tf-ref').textContent   = data.reference;

    if (data.expires_at) {
      document.getElementById('transfer-expires').textContent =
        'Expires ' + formatExpiry(data.expires_at);
    }

    /* Show transfer box, hide steps */
    document.getElementById('transfer-box').classList.add('visible');
    document.getElementById('transfer-steps').style.display = 'none';

    /* Update button to a cancel/done state */
    document.getElementById('transfer-btn-text').textContent = 'Waiting for transfer…';
    setBtnLoading('transfer-btn', 'transfer-btn-text', 'transfer-spinner', false);
    document.getElementById('transfer-btn').disabled = true;
    document.getElementById('transfer-btn').style.background = 'var(--border2)';

    /* Start polling */
    startPolling(txRef);

  } catch (e) {
    console.log(e);
    showAlert("An error occured. Please try again shortly.", 'error');
    setBtnLoading('transfer-btn', 'transfer-btn-text', 'transfer-spinner', false);
    document.getElementById('transfer-btn').disabled = false;
  }
}

/* ── Polling ── */
function startPolling(txRef) {
  var statusEl = document.getElementById('poll-status');
  var dotEl    = document.getElementById('poll-dot');
  var msgEl    = document.getElementById('poll-msg');

  statusEl.classList.add('visible');
  pollCount = 0;

  pollInterval = setInterval(async function () {
    pollCount++;

    if (pollCount > MAX_POLLS) {
      clearInterval(pollInterval);
      dotEl.className = 'poll-dot error';
      msgEl.textContent = 'Timed out. If you already transferred, contact support.';
      return;
    }

    try {
      var res  = await fetch('/payment/status/' + encodeURIComponent(txRef), {
        headers: { 'X-CSRFToken': getCSRFToken() }
      });
      var data = await res.json();

      if (data.status.toLowerCase().startsWith('succe')) { // I'm not quite sure that this will be a "succeeded" or a "success". This should match both anyway
        clearInterval(pollInterval);
        dotEl.className   = 'poll-dot success';
        msgEl.textContent = 'Transfer confirmed! Redirecting…';
        setTimeout(redirect, 1200);
      } else if (data.status.toLowerCase().startsWith('fail')) { // Once again, not sure if this is a "fail" or a "failed"
        clearInterval(pollInterval);
        dotEl.className   = 'poll-dot error';
        msgEl.textContent = 'Transfer failed or expired. Please try again.';
        document.getElementById('transfer-btn').disabled = false;
        document.getElementById('transfer-btn').style.background = '';
        document.getElementById('transfer-btn-text').textContent = 'Try again';
      }
      /* 'pending' → keep polling silently */

    } catch (_) { /* network blip — keep polling */ }

  }, POLL_EVERY_MS);
}

/* ── Redirect on success ── */
function redirect() {
  window.location.href = "/payment/success";
}

/* ── Copy helper ── */
function copyField(elemId, btn) {
  var text = document.getElementById(elemId).textContent.trim();
  navigator.clipboard.writeText(text).then(function () {
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(function () {
      btn.textContent = 'Copy';
      btn.classList.remove('copied');
    }, 2000);
  });
}

/* ── Alert helpers ── */
function showAlert(msg, type) {
  var el = document.getElementById('alert');
  el.textContent = msg;
  el.className = 'alert ' + type;
}
function clearAlert() {
  var el = document.getElementById('alert');
  el.className = 'alert'; el.textContent = '';
}

/* ── Button loading state ── */
function setBtnLoading(btnId, textId, spinnerId, loading) {
  document.getElementById(btnId).disabled = loading;
  document.getElementById(spinnerId).classList.toggle('visible', loading);
}

/* ── Expiry formatter ── */
function formatExpiry(isoString) {
  var d = new Date(isoString);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/* ── CSRF ── */
function getCSRFToken() {
  var el = document.querySelector('meta[name="csrf-token"]');
  return el ? el.getAttribute('content') : '';
}