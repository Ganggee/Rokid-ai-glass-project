// Meal page scenarios for run-aiui-checks.mjs (real backend, mocked camera returning synthetic photos).
import path from 'node:path';

const MEAL = 'pages/meal/meal.ink';

export async function mealScenarios({ check, assert, tick, openPage, makeRuntime, makeImage, ws, tmp, backend }) {
  const before = makeImage('meal_before', path.join(tmp, 'before.jpg'));
  const after = makeImage('meal_after', path.join(tmp, 'after.jpg'));

  await check('MEAL: new meal -> before photo -> label regions -> after photo -> analysis shown on HUD', async () => {
    const rt = makeRuntime({ photo: before });
    const p = await openPage(ws, MEAL, rt);
    assert(p.data().view === 'start', 'start view, got ' + p.data().view);
    await p.call('startMeal');
    assert(p.data().view === 'before', 'before view');
    await p.call('captureBefore');
    const d = p.data();
    assert(d.view === 'label' && d.regions.length >= 2, 'label view with detected regions, got ' + d.view + ' ' + d.regions.length);

    // re-entering the agent mid-meal resumes the same session (session id persisted on device)
    const p2 = await openPage(ws, MEAL, makeRuntime({ storage: rt.storage }));
    assert(p2.data().view === 'label' && p2.data().regions.length === d.regions.length, 'resumed at label step');

    // label region 0 with the first food option and 200 g; region 1 with the second option, no grams
    await p.call('cycleLabel', { index: 0 });
    for (let i = 0; i < 3; i++) await p.call('cycleGrams', { index: 0 });
    await p.call('cycleLabel', { index: 1 });
    await p.call('cycleLabel', { index: 1 });
    assert(/200g/.test(p.data().regions[0].text), 'grams shown: ' + p.data().regions[0].text);
    await p.call('saveItems');
    assert(p.data().view === 'after', 'after view, got ' + p.data().view + ' ' + p.data().message);

    rt.state.photo = after;
    await p.call('captureAfter');
    await tick(50);
    const r = p.data();
    assert(r.view === 'result', 'result view, got ' + r.view + ' msg=' + r.message);
    assert(r.resultLines.length === 2, 'two labelled foods, got ' + JSON.stringify(r.resultLines));
    assert(/%/.test(r.resultLines[0].line) && /g/.test(r.resultLines[0].line), 'ratio and grams on line 1: ' + r.resultLines[0].line);
    assert(/g 미입력|no grams/.test(r.resultLines[1].line), 'no grams on line 2 -> not computable: ' + r.resultLines[1].line);
    assert(r.isDemo === true, 'DEMO flagged (mock nutrition values)');
    const sid = rt.storage.get('meal.session.v1').sid;
    const s = await backend.api('/api/v1/meals/' + sid);
    assert(s.status === 'analyzed' && s.items.length === 2, 'server session analyzed');
    const res = await backend.api('/api/v1/meals/' + sid + '/results');
    assert(res.foods[0].initial_serving_grams === 200 && res.foods[1].kcal === null, 'server-side policy holds');
  });

  await check('MEAL: camera failure -> error message, stays on capture step', async () => {
    const rt = makeRuntime({ photo: null });
    const p = await openPage(ws, MEAL, rt);
    if (p.data().view !== 'start') await p.call('restart');
    await p.call('startMeal');
    await p.call('captureBefore');
    assert(p.data().view === 'before' && /카메라|Camera/.test(p.data().message), 'camera error, got ' + p.data().message);
  });

  await check('MEAL: analyse before after-photo -> server error shown, no fake result', async () => {
    const rt = makeRuntime({ photo: before });
    const p = await openPage(ws, MEAL, rt);
    if (p.data().view !== 'start') await p.call('restart');
    await p.call('startMeal');
    await p.call('captureBefore');
    await p.call('skipLabels');
    await p.call('analyze');
    assert(p.data().view === 'after' && /PHOTOS_REQUIRED/.test(p.data().message), 'error shown, got ' + p.data().message);
    assert(p.data().resultLines.length === 0, 'no result lines');
  });
}

export async function mealLocalScenarios({ check, assert, openPage, makeRuntime, AGENT }) {
  await check('MEAL (no server): page explains the server is required', async () => {
    const p = await openPage(AGENT, MEAL, makeRuntime());
    assert(p.data().view === 'noserver', 'noserver view, got ' + p.data().view);
  });
}
