/*
  STRING-BASED APPROACH
  =====================

  st.measure_string holds every character the user types, in order.
  Examples:
    "d:d:d:d"           = four quarter notes
    "d.d:d:d:-. "       = two eighth d, quarter d, quarter d sustained + rest
    "d,de.r:m'"         = sixteenth d, eighth de, quarter r, m with octave up

  The render() function parses this string character-by-character
  to build the visual notation. No token objects. No automatic insertion.

  PARSER HOOKS (empty — you will write the logic):
    checkMeasureLength(measure_string)  → called before commitMeasure()
    playMeasure(measure_string)         → called when playing a measure
*/

console.log(SOLFER_CTX)
var CHROMATIC = { de: 1, me: 1, fe: 1, si: 1, ta: 1 };
var PART_NAMES = { S: 'Soprano', A: 'Alto', T: 'Tenor', B: 'Bass' };
var KEY_ROOTS = { C: 0, 'C#/Db': 1, D: 2, 'D#/Eb': 3, E: 4, F: 5, 'F#/Gb': 6, G: 7, 'G#/Ab': 8, A: 9, 'A#/Bb': 10, B: 11 };
var SOLFA_ST = { d: 0, de: 1, r: 2, me: 3, m: 4, f: 5, fe: 6, s: 7, si: 8, l: 9, ta: 10, t: 11 };

var NOTES = [
  { n: 'd', ch: 0 }, { n: 'de', ch: 1 }, { n: 'r', ch: 0 }, { n: 'me', ch: 1 },
  { n: 'm', ch: 0 }, { n: 'f', ch: 0 }, { n: 'fe', ch: 1 }, { n: 's', ch: 0 },
  { n: 'si', ch: 1 }, { n: 'l', ch: 0 }, { n: 'ta', ch: 1 }, { n: 't', ch: 0 }
];
var TEMPO_PRESETS = [
  { label: 'Largo', bpm: 60 }, { label: 'Adagio', bpm: 80 }, { label: 'Moderato', bpm: 100 },
  { label: 'Allegro', bpm: 132 }, { label: 'Presto', bpm: 176 }
];

/* ── State ── */
var st = {
  part: 'S',
  octMod: 'def',
  tempo: 100,
  nextSize: 'q',      // 'q' | 'e' | 's' — affects next note entered
  measure_string: '',      // THE string. Every keystroke appends here.
  measures: SOLFER_CTX.measures,       // array of {measure_string, key, time, part}
  totalNotes: 0,
  editing: null,
};
var audioReady = false, synth = null;
var measureCounter = SOLFER_CTX.last_m_id; // Counts measures that have been created regardless of their status (e.g. even if deleted later)

/* ── Audio ── */
async function initAudio() {
  try {
    await Tone.start();
    synth = new Tone.Synth({
      oscillator: { type: 'sine' },
      envelope: { attack: 0.01, decay: 0.08, sustain: 0.55, release: 0.35 }
    }).toDestination();
    audioReady = true;
    document.getElementById('audio-banner').style.display = 'none';
    setStatus('Audio ready');
  } catch (e) { setStatus('Audio error: ' + e.message); }
}

function midiToFreq(m) { return 440 * Math.pow(2, (m - 69) / 12); }

function noteToFreq(noteName, up, sub) {
  var s = SOLFA_ST[noteName]; if (s === undefined) return null;
  var root = KEY_ROOTS[getKey()] || 0;
  var baseOct = (st.part === 'B') ? 3 : 4;
  var oct = baseOct;
  if (up) oct = baseOct + 1;
  else if (sub) oct = baseOct - sub;

  // MIDI pitch of the tonic 'd' in this octave — our reference floor
  var tonicMidi = (oct + 1) * 12 + root;

  // Raw MIDI pitch of the requested note
  var noteMidi = (oct + 1) * 12 + ((root + s) % 12);

  // If the note wrapped below the tonic, push it up one octave.
  // This ensures m, f, s, l, t, etc. always sit ABOVE d in the same register,
  // matching how tonic solfa works: d is always the reference floor.
  if (noteMidi < tonicMidi) noteMidi += 12;

  return midiToFreq(noteMidi);
}

function beatDur() { return 60 / st.tempo; }

function playFreq(freq, dur) {
  if (!audioReady || !synth || !freq) return;
  try { synth.triggerAttackRelease(freq, Math.max(0.05, dur)); } catch (e) { }
}

var failedMeasures = []; // queue of measures that failed to save to server, to retry later.
var committing = false, retrying = false;

/* ── Getters ── */
function getKey() { return document.getElementById('sel-key').value; }
function getTime() { return document.getElementById('sel-time').value; }

/* ── String input ── */
function appendChar(ch) {
  st.measure_string += ch;
  render();
  document.getElementById('beat-counter').textContent = st.measure_string.length + ' chars';
}

function appendNote(noteName) {
  // Build the note string to append
  var up = (st.octMod === 'up');
  var sub = st.octMod === 'd1' ? 1 : st.octMod === 'd2' ? 2 : 0;

  var s = noteName;
  if (up) s += "'";
  if (sub) s += ['₀', '₁', '₂'][sub] || sub;
  if (st.nextSize === 'e') s += '.';
  if (st.nextSize === 's') s += ',';

  st.measure_string += s;
  st.totalNotes++;

  // Audio feedback
  playFreq(noteToFreq(noteName, up, sub), beatDur() * (st.nextSize === 'e' ? 0.5 : st.nextSize === 's' ? 0.25 : 1) * 0.85);
  setStatus('Note: ' + noteName);

  render();
  updateInfo();
  document.getElementById('beat-counter').textContent = st.measure_string.length + ' chars';
}

function appendDot() { st.measure_string += '.'; render(); updateCharCount(); setStatus('Dot'); }
function appendComma() { st.measure_string += ','; render(); updateCharCount(); setStatus('Comma'); }
function appendColon() { st.measure_string += ':'; render(); updateCharCount(); setStatus('Colon'); }
function appendRest() { st.measure_string += ' '; render(); updateCharCount(); setStatus('Rest'); }
function appendSustain() { st.measure_string += '-'; render(); updateCharCount(); setStatus('Sustain'); }
function appendBar() { st.measure_string += '|'; render(); updateCharCount(); setStatus('Bar line'); }

function updateCharCount() {
  document.getElementById('beat-counter').textContent = st.measure_string.length + ' chars';
}

function deleteLast() {
  if (!st.measure_string.length) return;
  // If last char is part of a multi-char note (de, me, fe, si, ta), remove the whole thing
  var last = st.measure_string.slice(-1);
  var two = st.measure_string.slice(-2);
  if (/^(de|me|fe|si|ta)$/.test(two)) {
    st.measure_string = st.measure_string.slice(0, -2);
    st.totalNotes = Math.max(0, st.totalNotes - 1);
  } else if (/^[dremfslt]$/.test(last)) {
    st.measure_string = st.measure_string.slice(0, -1);
    st.totalNotes = Math.max(0, st.totalNotes - 1);
  } else {
    st.measure_string = st.measure_string.slice(0, -1);
  }
  render(); updateInfo(); updateCharCount(); setStatus('Deleted');
}

/* ── clearAll: if you were editing, cancel the edit and put the measure back ── */
function clearAll() {
  st.measure_string = '';
  if (st.editing) {
    restoreMeasure(st.editing);
    st.editing = null;
    setStatus('Edit cancelled');
  } else {
    setStatus('Cleared');
  }
  render(); updateInfo(); updateCharCount();
}


render();
renderMeasures();
updateInfo();

function maxBy(arr, key, defaultValue) {
  if (!arr.length) return defaultValue;
  let best = arr[0], bestKey = key(best);
  for (let i = 1; i < arr.length; i++) {
    const k = key(arr[i]);
    if (k > bestKey) { best = arr[i]; bestKey = k; }
  }
  return best;
}
//////////////////////
/* =====================================================================
   SOLFER FIXES
   Replace the functions of the same name in your script with these,
   and add the new helpers (marked NEW). Order of the NEW helpers
   doesn't matter because function declarations are hoisted.
   ===================================================================== */

/* ── NEW: state for an in-progress edit ──
   Add this one line inside your `st` object:
       editing: null,      // the measure currently being edited (or null)
   Add this near `failedMeasures`:
       var committing = false, retrying = false;
*/

/* ── NEW: make loaded and new measures use the same ID key ──
   Server rows use m_id; commitMeasure used measure_id. We keep both
   in sync so either side of the API works, and sort by position.
   CALL THIS ONCE right before the first `render(); renderMeasures();`
   (the lines just after deleteLast / clearAll). */
function normalizeMeasures() {
  st.measures.forEach(function (m) {
    if (m.m_id == null) m.m_id = m.measure_id;
    if (m.measure_id == null) m.measure_id = m.m_id;
  });
  sortMeasures();
}

/* ── NEW ── */
function sortMeasures() {
  st.measures.sort(function (a, b) { return (a.position || 0) - (b.position || 0); });
}

/* ── NEW: next free position (max + 1), so deletions never cause collisions ── */
function nextPosition() {
  var max = -1;
  st.measures.forEach(function (m) { if ((m.position || 0) > max) max = m.position || 0; });
  return max + 1;
}

/* ── NEW: a measure is "pending" if it never reached the server ── */
function isPending(m) { return failedMeasures.indexOf(m) !== -1; }

function removeFromFailed(m) {
  var k = failedMeasures.indexOf(m);
  if (k !== -1) failedMeasures.splice(k, 1);
}

/* ── NEW: put a measure back in its correct place ── */
function restoreMeasure(m) {
  if (st.measures.indexOf(m) === -1) st.measures.push(m);
  sortMeasures();
  renderMeasures(); updateInfo();
}

/* ── NEW: server calls ── */
function apiDelete(id) {
  // Resolves true on success. 404 counts as success (already gone).
  return fetch("/api/measures/" + id, {
    method: "DELETE",
    headers: { "X-CSRFToken": getCSRFToken() }
  }).then(function (r) { return r.ok || r.status === 404; })
    .catch(function () { return false; });
}

function apiPost(measure) {
  return fetch("/api/measures", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRFToken": getCSRFToken() },
    body: JSON.stringify(measure)
  });
}

function postMeasure(measure) {
  apiPost(measure).then(function (response) {
    if (response.ok) {
      setStatus('Measure saved to server');
      retryFailed();                       // server is reachable, flush the queue
    } else {
      setStatus('Failed to save measure to server (will retry)');
      if (!isPending(measure)) failedMeasures.push(measure);
    }
  }).catch(function (error) {
    setStatus('Error saving measure: ' + error.message + ' (will retry)');
    if (!isPending(measure)) failedMeasures.push(measure);   // network errors queue too now
  });
}

/* ── NEW: retry queue ── */
function retryFailed() {
  if (retrying || !failedMeasures.length) return;
  retrying = true;
  var queue = failedMeasures.slice();
  queue.reduce(function (chain, m) {
    return chain.then(function () {
      if (!isPending(m)) return;            // deleted/edited while waiting
      return apiPost(m).then(function (r) {
        if (r.ok) removeFromFailed(m);
      }).catch(function () { /* still offline, keep it queued */ });
    });
  }, Promise.resolve()).then(function () {
    retrying = false;
    if (!failedMeasures.length) setStatus('All measures synced');
  });
}
setInterval(retryFailed, 15000);
window.addEventListener('online', retryFailed);

////////////////
/* ── commitMeasure ── */
function commitMeasure() {
  if (committing) return;
  if (!st.measure_string.length) { setStatus('Nothing to commit'); return; }

  var ok = checkMeasureLength(st.measure_string);
  if (!ok) return;

  var editing = st.editing;                       // non-null when re-saving an edited measure
  var id = ++measureCounter;
  var measure = {
    measure_string: st.measure_string,
    key: getKey(),
    time_sig: getTime(),
    part: st.part,
    m_id: id,
    measure_id: id,                               // same value under both names
    position: editing ? editing.position : nextPosition()   // edits keep their slot
  };

  function finish() {
    st.measures.push(measure);
    sortMeasures();
    st.editing = null;
    st.measure_string = '';
    st.nextSize = 'q';
    setSize('q');
    render(); renderMeasures(); updateInfo(); updateCharCount();
    setStatus('Measure ' + (st.measures.indexOf(measure) + 1) + ' committed');
    postMeasure(measure);
  }

  if (editing && !isPending(editing)) {
    // The old version exists on the server: remove it first, then save the new one.
    committing = true;
    setStatus('Saving changes...');
    apiDelete(editing.m_id).then(function (deleted) {
      committing = false;
      if (!deleted) {
        setStatus('Could not update on server. Your edit is kept, try again.');
        return;                                   // st.editing and measure_string stay as-is
      }
      finish();
    });
  } else {
    if (editing) removeFromFailed(editing);       // old version never reached the server
    finish();
  }
}

/* ── deleteMeasure: the original bug (read st.measures[i] AFTER splice) ── */
function deleteMeasure(i) {
  var measure = st.measures[i];                   // grab it BEFORE removing
  if (!measure) return;

  st.measures.splice(i, 1);
  renderMeasures(); updateInfo();

  if (isPending(measure)) {                       // never saved: nothing to delete remotely
    removeFromFailed(measure);
    setStatus('Measure deleted');
    return;
  }

  setStatus('Deleting measure...');
  apiDelete(measure.m_id).then(function (ok) {
    if (ok) {
      setStatus('Measure deleted from server');
    } else {
      restoreMeasure(measure);                    // keep UI and server in sync
      setStatus('Failed to delete measure from server');
    }
  });
}


/* ── Controls ── */
function setPart(p, el) {
  st.part = p;
  document.querySelectorAll('.pbtn').forEach(function (b) { b.classList.remove('on'); });
  el.classList.add('on');
  updateInfo();
}

function setOct(mod, el) {
  st.octMod = mod;
  document.querySelectorAll('.oct-btn').forEach(function (b) { b.classList.remove('on'); });
  el.classList.add('on');
}

function setTempo(v) {
  st.tempo = parseInt(v);
  document.getElementById('tempo-disp').textContent = st.tempo;
  document.querySelectorAll('.preset-btn').forEach(function (b) {
    b.classList.toggle('active', parseInt(b.dataset.bpm) === st.tempo);
  });
}

function setSize(size) {
  st.nextSize = size;
  document.querySelectorAll('.dur-btn').forEach(function (b) {
    b.classList.toggle('active-size', b.dataset.size === size);
  });
  setStatus({ q: 'Quarter note', e: 'Eighth note', s: 'Sixteenth note' }[size] + ' selected');
}

function verifyBeatLength(beatString) {
  // The 12 chromatic solfa syllables (order matters for alternation —
  // longer matches must come before their prefixes: 'de' before 'd', etc.)
  const NOTE = /^(?:de|me|fe|si|ta|r|m|f|s|l|t|d)(?:'|[₁₂])?$/;

  function isRest(atom) { return atom === '' || atom === ' '; }
  function isSustain(atom) { return atom === '-'; }

  function validAtom(atom) {
    return isRest(atom) || isSustain(atom) || NOTE.test(atom);
  }

  // More than one dot = invalid
  const dotParts = beatString.split('.');
  if (dotParts.length > 2) return false;

  if (dotParts.length === 1) {
    // No dot: no commas allowed, exactly one atom
    if (beatString.includes(',')) return false;
    return validAtom(beatString);
  }

  // Dot present: verify each eighth half independently
  function verifyHalf(half) {
    if (!half.includes(',')) {
      return validAtom(half);
    }

    // Only one comma per half
    const parts = half.split(',');
    if (parts.length !== 2) return false;

    const [left, right] = parts;
    if (!validAtom(left) || !validAtom(right)) return false;

    // Both sides being rests makes the comma redundant — invalid
    if (isRest(left) && isRest(right)) return false;

    return true;
  }

  return verifyHalf(dotParts[0]) && verifyHalf(dotParts[1]);
}

/**var up = (st.octMod === 'up');
  var sub = st.octMod==='d1' ? 1 : st.octMod==='d2' ? 2 : 0
 * Check if a measure string has the correct total beat length.
 * Called automatically before commitMeasure() saves a measure.
 * @param {string} measure_string — the raw character string of the current measure
 * @returns {boolean} — true if length is correct, false otherwise
 */
function checkMeasureLength(measure_string) {
  let parts = measure_string.split(':');
  let timeSig = getTime().split('/');
  let beatsPerMeasure = parseInt(timeSig[0]);
  // let beatUnit = parseInt(timeSig[1]);
  if ((parts.length % beatsPerMeasure) !== 0) {
    // setStatus('Incorrect number of beats: expected a multiple of ' + beatsPerMeasure + ' but got ' + parts.length);
    setStatus('Incorrect number of beats: expected a multiple of ' + beatsPerMeasure + ' but got ' + parts.length);
    return false; // number of beats must equal numerator in time signature
  }
  let valid = true;
  let invalidBeats = [];
  parts.forEach((value, index) => {
    // console.log('Checking beat ' + (index+1) + ': ' + value);
    if (!verifyBeatLength(value)) {
      invalidBeats.push(index + 1);
      // setStatus('Invalid format in beat ' + (index+1));
      valid = false;
    }
  })
  if (!valid) {
    setStatus('Invalid beats found in measure: ' + invalidBeats.join(', '));
  }
  return valid;
}


/**
 * Play back a measure from its raw string.
 * Called when user clicks the play button on a saved measure.
 * @param {string} measure_string — the raw character string of the measure to play
 */
function playMeasure(measure_string) {
  if (!audioReady || !synth) { setStatus('Enable audio first'); return; }

  const bd = beatDur();
  const beats = measure_string.split(":");
  const tones = []; // { note: string, dur: number } — sustains already merged in

  // ── Step 1: Parse measure_string into flat tones[] with correct durations ──
  // beats.forEach((beat) => {
  //     const eighths = beat.split(".");

  //     if (eighths.length === 1) {
  //         // Whole beat — quarter note (or rest/sustain)
  //         tones.push({ note: beat.trim() === '' ? ' ' : beat, dur: bd });
  //     } else {
  //         // Two eighth halves
  //         [eighths[0], eighths[1]].forEach((half) => {
  //             const sixteenths = half.split(",");
  //             if (sixteenths.length === 1) {
  //                 tones.push({ note: half, dur: bd / 2 });
  //             } else {
  //                 tones.push({ note: sixteenths[0], dur: bd / 4 });
  //                 tones.push({ note: sixteenths[1], dur: bd / 4 });
  //             }
  //         });
  //     }
  // });

  beats.forEach((beat) => {
    const eighths = beat.split(".");

    if (eighths.length === 1) {
      // Whole beat — quarter note (or rest/sustain)
      tones.push({ note: beat.trim() === '' ? ' ' : beat, dur: bd });
    } else {
      // Two eighth halves
      [eighths[0], eighths[1]].forEach((half) => {
        const sixteenths = half.split(",");
        if (sixteenths.length === 1) {
          tones.push({ note: half, dur: bd / 2 });
        } else {
          tones.push({ note: sixteenths[0], dur: bd / 4 });
          tones.push({ note: sixteenths[1], dur: bd / 4 });
        }
      });
    }
  });

  // ── Step 2: Merge sustains into the previous pitched note ──
  // Walk forwards; when we see a '-' tone, add its duration to the most
  // recent non-rest, non-sutstain tone and mark this tone as consumed.
  let lastPitchedIdx = -1;
  tones.forEach((tone, i) => {
    const n = tone.note;
    const isRest = (n === '' || n === ' ');
    const isSustain = (n === '-');

    if (isSustain) {
      if (lastPitchedIdx >= 0) {
        tones[lastPitchedIdx].dur += tone.dur;
      }
      tone.consumed = true; // skip during playback
    } else if (isRest) {
      // Rests break the sustain chain — a sustain after a rest
      // extends the rest silently rather than a note.
      lastPitchedIdx = -1;
      tone.consumed = false;
    } else {
      lastPitchedIdx = i;
      tone.consumed = false;
    }
  });

  // ── Step 3: Assign absolute start times ──
  // let cursor = Tone.now() + 0.05; // small scheduling buffer
  // tones.forEach((tone) => {
  //     tone.startTime = cursor;
  //     cursor += tone.dur;
  // });
  let cursor = Tone.now() + 0.05;
  tones.forEach((tone) => {
    tone.startTime = cursor;
    if (!tone.consumed) {          // ← only advance for tones that will actually play/rest
      cursor += tone.dur;
    }
  });

  // ── Step 4: Strip octave indicators and resolve frequency ──
  function parseNote(raw) {
    if (!raw) return { syllable: '', octave: null };
    let syllable = raw;
    let up = false, sub = 0;

    // Check last character for octave modifier, strip it
    const last = syllable[syllable.length - 1];
    if (last === "'") { up = true; syllable = syllable.slice(0, -1); }
    else if (last === '₁') { sub = 1; syllable = syllable.slice(0, -1); }
    else if (last === '₂') { sub = 2; syllable = syllable.slice(0, -1); }

    return { syllable, up, sub };
  }

  // ── Step 5: Schedule with Tone.js ──
  tones.forEach((tone) => {
    if (tone.consumed) return;                          // sustain — already merged
    const n = tone.note;
    console.log('Playing note:', n, 'duration:', tone.dur.toFixed(2) + 's', 'at time:', tone.startTime.toFixed(2) + 's');
    if (n === '' || n === ' ') return;                  // rest — silence

    const { syllable, up, sub } = parseNote(n);
    const freq = noteToFreq(syllable, up, sub);        // your existing function
    if (!freq) return;

    synth.triggerAttackRelease(
      freq,
      Math.max(0.0, tone.dur * 0.98),  // slight detach so notes don't bleed
      tone.startTime
    );
  });

  setStatus('Playing measure...');
}

/* ── Rendering: parse measure_string into visual notation ── */
function render() {
  var line = document.getElementById('solfa-line');
  line.innerHTML = '';

  // Time signature
  var sig = getTime().split('/');
  var ts = document.createElement('span');
  ts.className = 'ts';
  ts.innerHTML = '<span style="display:block;line-height:1.05;font-size:13px;font-weight:600;">' + sig[0] + '</span>'
    + '<span style="display:block;line-height:1.05;font-size:13px;font-weight:600;">' + sig[1] + '</span>';
  line.appendChild(ts);

  // Parse measure_string character by character for display
  var i = 0;
  while (i < st.measure_string.length) {
    var ch = st.measure_string[i];
    var next = st.measure_string[i + 1] || '';
    var two = ch + next;

    // Two-char notes: de, me, fe, si, ta
    if (/^(de|me|fe|si|ta)$/.test(two)) {
      var n = document.createElement('span');
      n.className = 'note' + (CHROMATIC[two] ? ' ch' : '');
      n.textContent = two;
      line.appendChild(n);
      i += 2;
      continue;
    }

    // Single-char notes: d, r, m, f, s, l, t
    if (/^[drmfslt]$/.test(ch)) {
      var n2 = document.createElement('span');
      n2.className = 'note' + (CHROMATIC[ch] ? ' ch' : '');
      n2.textContent = ch;
      line.appendChild(n2);
      i++;
      continue;
    }

    // Octave up marker
    if (ch === "'") {
      var om = document.createElement('span');
      om.className = 'octmark-up'; om.textContent = '’';
      // Attach to previous element if possible
      if (line.lastChild && line.lastChild.classList && line.lastChild.classList.contains('note')) {
        line.lastChild.appendChild(om);
      } else {
        line.appendChild(om);
      }
      i++;
      continue;
    }

    // Subscript digits (₁, ₂)
    if (ch === '₁' || ch === '₂' || ch === '1' || ch === '2') {
      var subVal = (ch === '₁' || ch === '1') ? '1' : '2';
      var om2 = document.createElement('span');
      om2.className = 'octmark-dn'; om2.textContent = subVal;
      if (line.lastChild && line.lastChild.classList && line.lastChild.classList.contains('note')) {
        line.lastChild.appendChild(om2);
      } else {
        line.appendChild(om2);
      }
      i++;
      continue;
    }

    // Dot (size mark or separator)
    if (ch === '.') {
      var dot = document.createElement('span');
      dot.className = 'sizemark'; dot.textContent = '.';
      line.appendChild(dot);
      i++;
      continue;
    }

    // Comma (size mark)
    if (ch === ',') {
      var comma = document.createElement('span');
      comma.className = 'sizemark'; comma.textContent = ',';
      line.appendChild(comma);
      i++;
      continue;
    }

    // Colon (separator)
    if (ch === ':') {
      var col = document.createElement('span');
      col.className = 'colon'; col.textContent = ':';
      line.appendChild(col);
      i++;
      continue;
    }

    // Bar line
    if (ch === '|') {
      var bar = document.createElement('span');
      bar.className = 'colon'; bar.textContent = '|';
      line.appendChild(bar);
      i++;
      continue;
    }

    // Sustain
    if (ch === '-') {
      var sus = document.createElement('span');
      sus.className = 'sustain'; sus.textContent = '-';
      line.appendChild(sus);
      i++;
      continue;
    }

    // Rest (space)
    if (ch === ' ' || ch === '') {
      var r = document.createElement('span');
      r.className = 'rest'; r.textContent = ' ';
      line.appendChild(r);
      i++;
      continue;
    }

    // Unknown char — skip
    i++;
  }

  // Cursor
  var cur = document.createElement('span');
  cur.className = 'cursor';
  line.appendChild(cur);
}

function editMeasure(i) {
  if (st.editing) { setStatus('Commit or clear the measure you are editing first'); return; }
  if (st.measure_string.length) { setStatus('Commit or clear the current measure first'); return; }
  var m = st.measures[i];
  if (!m) return;
 
  st.editing = m;
  st.measures.splice(i, 1);                       // hidden from the list while editing;
  st.measure_string = m.measure_string;           // server copy stays until you commit
  render(); renderMeasures(); updateInfo(); updateCharCount();
  setStatus('Editing measure ' + (i + 1) + ' (Clear to cancel)');
}

function renderMeasures() {
  var list = document.getElementById('measures-list');
  list.innerHTML = '';
  if (!st.measures.length) {
    list.innerHTML = '<div class="empty-msg">No measures yet.</div>';
    return;
  }
  st.measures.forEach(function (m, i) {
    var row = document.createElement('div'); row.className = 'measure-row';
    var num = document.createElement('span'); num.className = 'm-num'; num.textContent = i + 1;
    var prev = document.createElement('span'); prev.className = 'm-preview'; prev.textContent = m.measure_string;
    var acts = document.createElement('div'); acts.className = 'm-actions';

    var pb = document.createElement('button'); pb.textContent = '▶';
    pb.addEventListener('click', (function (idx) { return function () { playMeasure(st.measures[idx].measure_string); }; })(i));
    var eb = document.createElement('button'); eb.textContent = 'edit';
    eb.addEventListener('click', (function (idx) { return function () { editMeasure(idx); }; })(i));
    var db = document.createElement('button'); db.className = 'del-btn'; db.textContent = '✕';
    db.addEventListener('click', (function (idx) { return function () { deleteMeasure(idx); }; })(i));

    acts.appendChild(pb); acts.appendChild(eb); acts.appendChild(db);
    row.appendChild(num); row.appendChild(prev); row.appendChild(acts);
    list.appendChild(row);
  });
}

function updateInfo() {
  document.getElementById('i-key').textContent = getKey();
  document.getElementById('i-time').textContent = getTime();
  document.getElementById('i-part').textContent = PART_NAMES[st.part];
  document.getElementById('i-meas').textContent = st.measures.length;
  document.getElementById('i-notes').textContent = st.totalNotes;
}

function setStatus(msg) { document.getElementById('status-msg').textContent = msg; }

/* ── Build keyboards ── */
function buildKeyboard() {
  // Note keys
  var nk = document.getElementById('note-keys');
  NOTES.forEach(function (obj) {
    var b = document.createElement('div');
    b.className = 'k' + (obj.ch ? ' ch' : '');
    b.textContent = obj.n;
    b.addEventListener('click', (function (name) { return function () { appendNote(name); }; })(obj.n));
    nk.appendChild(b);
  });

  // Duration keys
  // var dk = document.getElementById('dur-keys');
  // [{label:'♩ quarter',size:'q'},{label:'♪ eighth',size:'e'},{label:'♬ sixteenth',size:'s'}].forEach(function(obj){
  //   var b = document.createElement('div');
  //   b.className = 'k sp dur-btn' + (obj.size==='q' ? ' active-size' : '');
  //   b.dataset.size = obj.size;
  //   b.textContent = obj.label;
  //   b.addEventListener('click', (function(sz){return function(){setSize(sz);};})(obj.size));
  //   dk.appendChild(b);
  // });

  // Modifier keys
  var mk = document.getElementById('mod-keys');
  var mods = [
    { label: '.', title: 'Dot', fn: appendDot },
    { label: ',', title: 'Comma', fn: appendComma },
    { label: ':', title: 'Colon separator', fn: appendColon },
    { label: ' ', title: 'Rest (space)', fn: appendRest },
    { label: '-', title: 'Sustain', fn: appendSustain },
    { label: "' ↑", title: 'Octave up', fn: function () { setOct('up', document.getElementById('oct-up')); } },
    { label: '₁ ↓', title: '1 octave down', fn: function () { setOct('d1', document.getElementById('oct-d1')); } },
    { label: '₂ ↓↓', title: '2 octaves down', fn: function () { setOct('d2', document.getElementById('oct-d2')); } },
    { label: '| bar', title: 'Commit measure', fn: commitMeasure },
    { label: '⌫', title: 'Delete last', fn: deleteLast, extra: 'del-key' },
    { label: 'Clear', title: 'Clear all', fn: clearAll }
  ];
  mods.forEach(function (obj) {
    var b = document.createElement('div');
    b.className = 'k sp' + (obj.extra ? ' ' + obj.extra : '');
    b.textContent = obj.label; b.title = obj.title;
    b.addEventListener('click', obj.fn);
    mk.appendChild(b);
  });
}

function buildTempoPresets() {
  var wrap = document.getElementById('tempo-presets');
  TEMPO_PRESETS.forEach(function (p) {
    var b = document.createElement('button');
    b.className = 'preset-btn'; b.dataset.bpm = p.bpm; b.textContent = p.label;
    b.addEventListener('click', function () {
      st.tempo = p.bpm;
      document.getElementById('tempo-slider').value = p.bpm;
      setTempo(p.bpm);
    });
    wrap.appendChild(b);
  });
}

/* ── Keyboard shortcuts ── */
document.addEventListener('keydown', function (e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
  if (document.querySelector('dialog[open]')) return;

  var keyMap = { d: 'd', r: 'r', m: 'm', f: 'f', s: 's', l: 'l', t: 't' };
  if (keyMap[e.key]) { e.preventDefault(); appendNote(keyMap[e.key]); return; }

  if (e.key === ' ') { e.preventDefault(); appendRest(); return; }
  if (e.key === '.') { e.preventDefault(); appendDot(); return; }
  if (e.key === ',') { e.preventDefault(); appendComma(); return; }
  if (e.key === ':') { e.preventDefault(); appendColon(); return; }
  if (e.key === '-' || e.key === '_') { e.preventDefault(); appendSustain(); return; }
  if (e.key === '|' || e.key === '\\') { e.preventDefault(); commitMeasure(); return; }
  if (e.key === 'Backspace') { e.preventDefault(); deleteLast(); return; }
  if (e.key === 'Enter') { e.preventDefault(); commitMeasure(); return; }

  // Arrow keys for octave shifting
  if (e.key === 'ArrowUp') {
    e.preventDefault();
    var order = ['d2', 'd1', 'def', 'up'];
    var next = order[Math.min(order.indexOf(st.octMod) + 1, order.length - 1)];
    setOct(next, document.getElementById('oct-' + next));
    return;
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    var order = ['d2', 'd1', 'def', 'up'];
    var prev = order[Math.max(order.indexOf(st.octMod) - 1, 0)];
    setOct(prev, document.getElementById('oct-' + prev));
    return;
  }
});

/* ── Init ── */
buildKeyboard();
buildTempoPresets();
render();
updateInfo();


/* ── downloadWav: stop after a failed response instead of trying to download an error ── */
async function downloadWav() {
  if (!st.measures.length) { setStatus('No measures to export'); return; }

  let combinedMeasures = { measure_string: '', key: getKey(), time_sig: getTime(), part: st.part, tempo: st.tempo };
  st.measures.forEach((m, i) => {
    combinedMeasures.measure_string += m.measure_string + (i !== st.measures.length - 1 ? ":" : "");
  });

  let response;
  try {
    response = await fetch("/convert-audio", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCSRFToken() },
      body: JSON.stringify(combinedMeasures),
    });
  } catch (e) {
    setStatus("Network error during audio export: " + e.message);
    return;
  }

  if (!response.ok) {
    setStatus("Server error during audio export: " + response.statusText);
    return;                                       // was missing: previously fell through
  }

  const disposition = response.headers.get('content-disposition');
  let filename = 'measure.wav';
  if (disposition && disposition.includes('filename=')) {
    const match = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
    if (match && match[1]) filename = match[1].replace(/['"]/g, '');
  }

  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(url);
  a.remove();
}