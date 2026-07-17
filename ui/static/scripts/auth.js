/* ── Tab switching ── */
function switchTab(tab) {
  var isLogin = tab === 'login';

  document.getElementById('tab-login').classList.toggle('active', isLogin);
  document.getElementById('tab-signup').classList.toggle('active', !isLogin);
  document.getElementById('panel-login').classList.toggle('active', isLogin);
  document.getElementById('panel-signup').classList.toggle('active', !isLogin);

  document.getElementById('card-title').textContent =
    isLogin ? 'Welcome back' : 'Create your account';
  document.getElementById('card-sub').textContent =
    isLogin ? 'Sign in to access your compositions' : 'Start notating music for free';
  document.getElementById('switch-mode').innerHTML = isLogin
    ? 'Don\'t have an account? <a href="#" onclick="switchTab(\'signup\'); return false;">Sign up free</a>'
    : 'Already have an account? <a href="#" onclick="switchTab(\'login\'); return false;">Log in</a>';

  clearAlert();
  clearErrors();
}


/* ── Alert helpers ── */
function showAlert(msg, type) {
  var el = document.getElementById('alert');
  el.textContent = msg;
  el.className = 'alert ' + type;
}
function clearAlert() {
  var el = document.getElementById('alert');
  el.className = 'alert';
  el.textContent = '';
}

/* ── Field error helpers ── */
function fieldError(id, msg) {
  var el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.classList.toggle('visible', !!msg);
  /* highlight the input */
  var input = el.previousElementSibling;
  if (input && input.tagName === 'INPUT') input.classList.toggle('error', !!msg);
}
function clearErrors() {
  document.querySelectorAll('.field-error').forEach(function(e) {
    e.classList.remove('visible'); e.textContent = '';
  });
  document.querySelectorAll('input').forEach(function(i) {
    i.classList.remove('error');
  });
}

/* ── Password strength indicator ── */
var STRENGTH_COLORS = ['#a32d2d','#c87020','#b8960a','#1a7a3c'];
var STRENGTH_LABELS = ['Weak','Fair','Good','Strong'];

function checkStrength(val) {
  var score = 0;
  if (val.length >= 8)                  score++;
  if (/[A-Z]/.test(val))               score++;
  if (/[0-9]/.test(val))               score++;
  if (/[^A-Za-z0-9]/.test(val))        score++;

  for (var i = 1; i <= 4; i++) {
    var seg = document.getElementById('seg' + i);
    seg.style.background = i <= score ? STRENGTH_COLORS[score - 1] : 'var(--border)';
  }
  var lbl = document.getElementById('strength-label');
  lbl.textContent  = val.length ? STRENGTH_LABELS[score - 1] || '' : '';
  lbl.style.color  = score ? STRENGTH_COLORS[score - 1] : 'var(--text3)';
}

/* ── Form handlers (placeholders — wire to Flask routes) ── */
function handleLogin(e) {
  e.preventDefault();
  clearErrors(); clearAlert();

  var email    = document.getElementById('login-email').value.trim();
  var password = document.getElementById('login-password').value;
  var valid    = true;

  if (!email) { fieldError('login-email-err', 'Email is required'); valid = false; }
  if (!password) { fieldError('login-password-err', 'Password is required'); valid = false; }
  if (!valid) return;

  /* TODO: POST /auth/login  { email, password } */
  // showAlert('Login route not yet connected (Flask endpoint: POST /auth/login)', 'error');
  response = fetch('/auth/login', {
    method: 'POST',
    headers: { 
      'Content-Type': 'application/json', 
      'X-CSRFToken': getCSRFToken()
     },
    body: JSON.stringify({ email: email, password: password })
  });
  response.then((res)=>{
    if (res.ok) {
      showAlert('Login successful! Redirecting...', 'success');
      setTimeout(() => { window.location.href = '/'; }, 1000);
    } else if (res.status === 401) {
      showAlert('Invalid email or password', 'error');
    } else {
      showAlert('An error occurred. Please try again.', 'error');
    }
  })
}

function handleSignup(e) {
  e.preventDefault();
  clearErrors(); clearAlert();

  var name     = document.getElementById('signup-name').value.trim();
  var email    = document.getElementById('signup-email').value.trim();
  var password = document.getElementById('signup-password').value;
  var confirm  = document.getElementById('signup-confirm').value;
  var valid    = true;

  if (!name)    { fieldError('signup-name-err', 'Name is required'); valid = false; }
  if (!email)   { fieldError('signup-email-err', 'Email is required'); valid = false; }
  if (password.length < 8) {
    fieldError('signup-password-err', 'Password must be at least 8 characters'); valid = false;
  }
  if (password !== confirm) {
    fieldError('signup-confirm-err', 'Passwords do not match'); valid = false;
  }
  if (!valid) return;

  /* TODO: POST /auth/signup  { name, email, password } */
  // showAlert('Signup route not yet connected (Flask endpoint: POST /auth/signup)', 'error');
  response = fetch('/auth/signup', {
    method: 'POST',
    headers: { 
      'Content-Type': 'application/json',
      'X-CSRFToken': getCSRFToken()
    },
    body: JSON.stringify({ name: name, email: email, password: password })
  });
  response.then((res)=>{
    if (res.ok) {
      showAlert('Signup successful! Redirecting...', 'success');
      setTimeout(() => { window.location.href = '/'; }, 1000);
    } 
    else if (res.status === 400) {
      res.json().then(data => {
        if (data.error) {
          showAlert(data.error, 'error');
        } else {
          showAlert('Invalid input. Please check your data and try again.', 'error');
        }
      });
    } else if (res.status === 409) {
      res.json().then(data=>{
        if (data.error) showAlert(data.error, 'error');
        else showAlert("Perhaps an account with email already exists?", 'error');
      })
    }
})
}

function handleGoogle() {
  /* TODO: redirect to /auth/google  (Flask-Dance or Authlib OAuth flow) */
  showAlert('Google OAuth not yet connected (Flask endpoint: GET /auth/google)', 'error');
  return false;
}

// function handleForgot() {
//   /* TODO: GET /auth/forgot-password */
//   showAlert('Password reset not yet connected (Flask endpoint: POST /auth/forgot-password)', 'error');
//   return false;
// }

function handlePlaceholder(name) {
  showAlert(name + ' page not yet available', 'error');
  return false;
}