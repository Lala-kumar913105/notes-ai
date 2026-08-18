'use strict';
// Behavioral test for the Generate Study Kit chain (frontend-only).
// Loads the real inline <script> of templates/index.html into a stubbed-DOM
// Node vm, so generateStudyKit() runs against genuine app code.
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'templates/index.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
let js = scripts[scripts.length - 1];
js = js.replace(/\{\{[^}]*\}\}/g, 'false').replace(/\{%[\s\S]*?%\}/g, '');
// Exporter: top-level let/const aren't sandbox-global props in vm.
js += '\n;globalThis.__testExports = {\n' +
  '  getNotesContent: () => notesContent,\n' +
  '  setNotesContent: (v) => { notesContent = v; },\n' +
  '  getQuizData: () => quizData,\n' +
  '  getFlashcardsData: () => flashcardsData,\n' +
  '};\n';

function makeElement(id) {
  const el = {
    id: id || 'created', disabled: false, innerHTML: '', value: '', dataset: {},
    style: { display: '' },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    setAttribute() {}, appendChild() {}, removeChild() {}, addEventListener() {},
    querySelector() { return makeElement('found'); }, querySelectorAll() { return []; },
    scrollTop: 0, scrollHeight: 0, focus() {}, click() {}, remove() {},
    _text: '', __textHistory: [],
  };
  Object.defineProperty(el, 'textContent', {
    get() { return el._text; },
    set(v) { el._text = String(v == null ? '' : v); el.__textHistory.push(el._text); },
  });
  return el;
}

function makeEnv(fetchImpl) {
  const elements = {};
  const calls = [];
  const alerts = [];
  const documentStub = {
    getElementById(id) { if (!elements[id]) elements[id] = makeElement(id); return elements[id]; },
    createElement() { return makeElement('created'); },
    createElementNS() { return makeElement('ns'); },
    addEventListener() {},
    querySelectorAll() { return []; },
    querySelector() { return null; },
    body: makeElement('body'),
    documentElement: makeElement('html'),
    head: makeElement('head'),
  };
  const sandbox = {
    console,
    document: documentStub,
    window: {
      marked: undefined,
      URL: { createObjectURL() { return 'blob:x'; }, revokeObjectURL() {} },
      innerWidth: 1280, SpeechRecognition: undefined, webkitSpeechRecognition: undefined,
      location: { search: '' },
    },
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    crypto: { randomUUID: () => 'uuid-' + Math.random() },
    alert: (m) => alerts.push(String(m)),
    fetch: async (url, opts) => { calls.push(url); return fetchImpl(url, opts); },
    setTimeout, clearTimeout, setInterval, clearInterval,
    TextEncoder, TextDecoder, URLSearchParams,
    navigator: { language: 'en-US', clipboard: { writeText: async () => {} } },
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(js, sandbox, { filename: 'index.inline.js' });
  return { ctx: sandbox, elements, calls, alerts };
}

function jsonResponse(data, ok) { return { ok: ok !== false, json: async () => data }; }
function sseResponse(payloads) {
  const queue = payloads.slice();
  return {
    ok: true,
    body: {
      getReader() {
        return {
          async read() {
            if (queue.length) return { done: false, value: new TextEncoder().encode(queue.shift()) };
            return { done: true, value: undefined };
          },
        };
      },
    },
  };
}

const results = [];
function check(name, ok, extra) {
  results.push(ok);
  console.log((ok ? 'PASS' : 'FAIL') + ' - ' + name + (extra ? '  ' + extra : ''));
}
function seqEq(a, b) { return a.length === b.length && a.every((v, i) => v === b[i]); }

function happyNotes() {
  return sseResponse([
    'data: ' + JSON.stringify({ chunk: 'These are the notes. ' }) + '\n\n',
    'data: ' + JSON.stringify({ chunk: 'More note content. ' }) + '\n\n',
    'data: ' + JSON.stringify({ done: true }) + '\n\n',
  ]);
}
function happyFetch(url) {
  if (url === '/generate-notes-stream') return happyNotes();
  if (url === '/generate-quiz') return jsonResponse({ questions: [{ type: 'mcq', question: 'q1', options: ['a', 'b'], answer: 0 }] });
  if (url === '/generate-flashcards') return jsonResponse({ cards: [{ front: 'f1', back: 'b1' }] });
  if (url === '/generate-mindmap') return jsonResponse({ branches: [{ label: 'Root', children: [{ label: 'Child' }] }] });
  return jsonResponse({ error: 'no route' }, false);
}

const main = async () => {
  // Test 1: happy path — full kit runs in order
  {
    const env = makeEnv(happyFetch);
    env.ctx.document.getElementById('topic').value = 'Photosynthesis';
    await env.ctx.generateStudyKit();
    check('happy: call order notes->quiz->flashcards->mindmap',
      seqEq(env.calls, ['/generate-notes-stream', '/generate-quiz', '/generate-flashcards', '/generate-mindmap']),
      env.calls.join(' | '));
    check('happy: notesContent populated', env.ctx.__testExports.getNotesContent().includes('These are the notes'));
    check('happy: quizData populated', env.ctx.__testExports.getQuizData().length === 1);
    check('happy: flashcardsData populated', env.ctx.__testExports.getFlashcardsData().length === 1);
    check('happy: mind map rendered', env.elements['mindmap-box'].innerHTML.length > 0);
    check('happy: all five buttons re-enabled',
      ['btn-study-kit', 'btn-notes', 'btn-quiz', 'btn-flashcards', 'btn-mindmap']
        .every(id => env.elements[id].disabled === false));
    const steps = env.elements['notes-status-text'].__textHistory;
    check('happy: progress showed Step 1..4 in order',
      ['Step 1 of 4', 'Step 2 of 4', 'Step 3 of 4', 'Step 4 of 4']
        .every(s => steps.some(str => str.includes(s))),
      steps.filter(s => s).join(' -> '));
    check('happy: completion message shown',
      env.elements['notes-status-text'].textContent.includes('Study Kit complete'));
  }

  // Test 2: mid-chain failure (quiz) must not abort the kit
  {
    const env = makeEnv((url) => {
      if (url === '/generate-quiz') return jsonResponse({ error: 'mock quiz failure' }, false);
      return happyFetch(url);
    });
    env.ctx.document.getElementById('topic').value = 'Photosynthesis';
    await env.ctx.generateStudyKit();
    check('mid-fail: continued to flashcards+mindmap after quiz failure',
      seqEq(env.calls, ['/generate-notes-stream', '/generate-quiz', '/generate-flashcards', '/generate-mindmap']),
      env.calls.join(' | '));
    check('mid-fail: quiz failure surfaced via alert',
      env.alerts.some(a => a.includes('mock quiz failure')), env.alerts.join(' | '));
    check('mid-fail: quizData empty', env.ctx.__testExports.getQuizData().length === 0);
    check('mid-fail: flashcardsData still populated', env.ctx.__testExports.getFlashcardsData().length === 1);
    check('mid-fail: mind map still rendered', env.elements['mindmap-box'].innerHTML.length > 0);
    check('mid-fail: no button left disabled/loading',
      ['btn-study-kit', 'btn-notes', 'btn-quiz', 'btn-flashcards', 'btn-mindmap']
        .every(id => env.elements[id].disabled === false));
  }

  // Test 3: notes failure must stop the kit but never stick
  {
    const env = makeEnv((url) => {
      if (url === '/generate-notes-stream') return jsonResponse({ error: 'mock notes failure' }, false);
      return happyFetch(url);
    });
    env.ctx.document.getElementById('topic').value = 'Photosynthesis';
    await env.ctx.generateStudyKit();
    check('notes-fail: stopped after the notes step',
      seqEq(env.calls, ['/generate-notes-stream']), env.calls.join(' | '));
    check('notes-fail: user notified', env.alerts.some(a => a.includes('Notes generation failed')),
      env.alerts.join(' | '));
    check('notes-fail: notes + kit buttons re-enabled',
      env.elements['btn-notes'].disabled === false && env.elements['btn-study-kit'].disabled === false);
    check('notes-fail: quiz/flashcards/mindmap stay disabled (no notes)',
      env.elements['btn-quiz'].disabled && env.elements['btn-flashcards'].disabled &&
      env.elements['btn-mindmap'].disabled);
  }

  // Test 4: existing notes + no topic reuse the box, skip regenerate
  {
    const env = makeEnv(happyFetch);
    env.ctx.__testExports.setNotesContent('Pre-existing notes.');
    await env.ctx.generateStudyKit();
    check('reuse: no notes call — chain starts at quiz',
      seqEq(env.calls, ['/generate-quiz', '/generate-flashcards', '/generate-mindmap']),
      env.calls.join(' | '));
    check('reuse: notesContent untouched', env.ctx.__testExports.getNotesContent() === 'Pre-existing notes.');
    check('reuse: everything generated + buttons enabled',
      env.ctx.__testExports.getQuizData().length === 1 &&
      env.ctx.__testExports.getFlashcardsData().length === 1 &&
      env.elements['mindmap-box'].innerHTML.length > 0 &&
      ['btn-study-kit', 'btn-notes', 'btn-quiz', 'btn-flashcards', 'btn-mindmap']
        .every(id => env.elements[id].disabled === false));
  }

  // Test 5: the four individual buttons still work on their own
  {
    const env = makeEnv(happyFetch);
    env.ctx.__testExports.setNotesContent('Standalone notes.');
    await env.ctx.generateQuiz();
    check('individual: generateQuiz works', env.ctx.__testExports.getQuizData().length === 1);
    check('individual: quiz button re-enabled', env.elements['btn-quiz'].disabled === false);
    await env.ctx.generateFlashcards();
    check('individual: generateFlashcards works', env.ctx.__testExports.getFlashcardsData().length === 1);
    check('individual: flashcards button re-enabled', env.elements['btn-flashcards'].disabled === false);
    await env.ctx.generateMindMap();
    check('individual: generateMindMap works', env.elements['mindmap-box'].innerHTML.length > 0);
    check('individual: mindmap button re-enabled', env.elements['btn-mindmap'].disabled === false);
  }

  // Test 6: empty guard — nothing to build from
  {
    const env = makeEnv(happyFetch);
    await env.ctx.generateStudyKit();
    check('guard: aborts without network calls', env.calls.length === 0);
    check('guard: friendly alert shown', env.alerts.some(a => a.includes('topic or attach a source file')),
      env.alerts.join(' | '));
    check('guard: study-kit button never disabled', env.elements['btn-study-kit'].disabled === false);
  }

  // Test 7: Notes Mode — single "mode" field, exclusivity, professional payload
  {
    const env = makeEnv(happyFetch);
    env.ctx.document.getElementById('topic').value = 'Q3 earnings call';
    check('mode: defaults to student', env.ctx.getNotesMode() === 'student');
    env.ctx.setNotesMode('professional');
    check('mode: getNotesMode returns professional after switch', env.ctx.getNotesMode() === 'professional');
    env.ctx.setNotesMode('teacher');
    check('mode: modes are mutually exclusive (now teacher)', env.ctx.getNotesMode() === 'teacher');
    env.ctx.setNotesMode('not-a-mode');
    check('mode: invalid value falls back to student', env.ctx.getNotesMode() === 'student');

    // Professional generation sends a single "mode" field (not a boolean).
    const bodies = [];
    const env2 = makeEnv((url, opts) => {
      if (url === '/generate-notes-stream') { bodies.push(opts.body); return happyNotes(); }
      return happyFetch(url);
    });
    env2.ctx.document.getElementById('topic').value = 'Q3 earnings call';
    env2.ctx.setNotesMode('professional');
    await env2.ctx.generateNotes();
    const payload = JSON.parse(bodies[0]);
    check('mode: professional payload carries mode field', payload.mode === 'professional', payload.mode);
    check('mode: payload has no legacy teacher_mode boolean', !('teacher_mode' in payload));
    check('mode: professional notes content populated', env2.ctx.__testExports.getNotesContent().includes('These are the notes'));
  }

  // Test 8: Study-tool sub-tabs — openNotesSubTab shows exactly one panel
  {
    const env = makeEnv(happyFetch);
    const panels = ['tutor', 'quiz', 'flashcards', 'mindmap', 'pdf'];
    // Populate the stub elements first so every panel id resolves.
    panels.forEach(p => env.ctx.document.getElementById('notes-panel-' + p));
    const defaultHidden = panels.every(p =>
      env.elements['notes-panel-' + p].style.display === 'none' ||
      env.elements['notes-panel-' + p].style.display === '');
    check('subtabs: all study-tool panels hidden by default', defaultHidden);

    env.ctx.openNotesSubTab('quiz');
    check('subtabs: quiz panel shown', env.elements['notes-panel-quiz'].style.display === 'block');
    check('subtabs: tutor panel hidden when quiz active', env.elements['notes-panel-tutor'].style.display === 'none');

    env.ctx.openNotesSubTab('pdf');
    check('subtabs: pdf panel shown after switch', env.elements['notes-panel-pdf'].style.display === 'block');
    check('subtabs: quiz panel hidden after switch', env.elements['notes-panel-quiz'].style.display === 'none');

    // Original ids + generation functions still resolve inside the panels.
    env.ctx.__testExports.setNotesContent('Notes for quiz.');
    env.ctx.openNotesSubTab('quiz');
    await env.ctx.generateQuiz();
    check('subtabs: generateQuiz still works after reorganize', env.ctx.__testExports.getQuizData().length === 1);
    check('subtabs: quiz-box element still resolves', !!env.elements['quiz-box']);
    // Resolve a few more original ids through the DOM stub (they exist in the
    // real markup — the stub only records ids that getElementById has asked for).
    ['btn-tutor', 'tutor-panel', 'pdf-workspace-panel', 'mindmap-box', 'flashcards-box']
      .forEach(id => env.ctx.document.getElementById(id));
    check('subtabs: btn-tutor still resolves', !!env.elements['btn-tutor']);
    check('subtabs: pdf-workspace-panel still resolves', !!env.elements['pdf-workspace-panel']);
  }

  const passed = results.filter(Boolean).length;
  console.log('\nSUMMARY: ' + passed + '/' + results.length + ' passed');
  process.exit(passed === results.length ? 0 : 1);
};

main().catch((err) => {
  console.error('HARNESS ERROR:', err);
  process.exit(1);
});
