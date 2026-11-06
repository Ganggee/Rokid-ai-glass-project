// Diary page scenarios (real backend; SpeechRecognition and speechSynthesis mocked).
const DIARY = 'pages/diary/diary.ink';

function yesterdayParts() {
  const now = new Date(Date.now() + 9 * 3600 * 1000); // Asia/Seoul
  const y = new Date(now.getTime() - 24 * 3600 * 1000);
  return { iso: y.toISOString().slice(0, 10), m: y.getUTCMonth() + 1, d: y.getUTCDate() };
}
const logPosts = (rt) => rt.state.requests.filter((r) => r.method === 'POST' && /\/api\/v1\/meal-logs$/.test(r.url)).length;

export async function diaryScenarios({ check, assert, tick, openPage, makeRuntime, ws, backend }) {
  const y = yesterdayParts();

  await check('DIARY: voice record -> confirm screen (0 POST) -> cancel (0 POST) -> record again -> save (1 POST)', async () => {
    const say = `${y.m}월 ${y.d}일 저녁 김밥 1인분이랑 배추김치 먹었어`;
    const rt = makeRuntime({ speechEnabled: true, tts: true, speech: [say, '취소', say, '확인'] });
    const p = await openPage(ws, DIARY, rt);
    await p.call('voice'); await tick(30);
    let d = p.data();
    assert(d.view === 'confirm' && d.items.length === 2, 'confirm view with 2 items, got ' + d.view + ' ' + d.message);
    assert(/저녁/.test(d.heading) && d.heading.includes(`${y.m}월 ${y.d}일`), 'heading shows full date+meal: ' + d.heading);
    assert(logPosts(rt) === 0, 'no POST before confirmation');
    await p.call('voice'); await tick(30);
    assert(p.data().view === 'home' && logPosts(rt) === 0, 'cancel writes nothing');
    await p.call('voice'); await tick(30);
    await p.call('voice'); await tick(60); // "확인"
    d = p.data();
    assert(logPosts(rt) === 1, 'exactly one POST, got ' + logPosts(rt));
    assert(d.view === 'view' && d.lines.some((l) => /김밥/.test(l.line)), 'summary shown after save: ' + JSON.stringify(d.lines));
    const logs = (await backend.api('/api/v1/meal-logs?date=' + y.iso)).items.filter((l) => l.source === 'voice');
    assert(logs.length === 1 && logs[0].meal_type === 'dinner' && logs[0].items[0].kcal !== null, 'server has the log with kcal: ' + JSON.stringify(logs).slice(0, 600));
  });

  await check('DIARY: "어제 저녁 기록 읽어줘" -> summary on HUD and speechSynthesis.speak called once (<=150 chars)', async () => {
    const rt = makeRuntime({ speechEnabled: true, tts: true, speech: ['어제 저녁 기록 읽어줘'] });
    const p = await openPage(ws, DIARY, rt);
    await p.call('voice'); await tick(60);
    assert(p.data().view === 'view', 'view shown');
    assert(rt.state.spoken.length === 1 && rt.state.spoken[0].mode === 'enqueue', 'speak once, got ' + JSON.stringify(rt.state.spoken));
    assert(rt.state.spoken[0].text.length <= 150 && /저녁/.test(rt.state.spoken[0].text), 'speech text: ' + rt.state.spoken[0].text);
  });

  await check('DIARY: no TTS runtime -> HUD message, no crash', async () => {
    const rt = makeRuntime({ speechEnabled: true, tts: false, speech: ['어제 기록 읽어줘'] });
    const p = await openPage(ws, DIARY, rt);
    await p.call('voice'); await tick(60);
    assert(p.data().view === 'view' && /음성 출력 불가|TTS unavailable/.test(p.data().message), 'fallback: ' + p.data().message);
  });

  await check('DIARY: future date / missing meal -> question, never a POST', async () => {
    const rt = makeRuntime({ speechEnabled: true, tts: true });
    const p = await openPage(ws, DIARY, rt);
    await p.call('handleText', '내일 아침 김밥 먹었어');
    assert(p.data().view === 'ask' && /미래/.test(p.data().question), 'future question: ' + p.data().question);
    await p.call('handleText', '오늘 김밥 기록');
    assert(p.data().view === 'ask' && /끼니/.test(p.data().question), 'meal question: ' + p.data().question);
    assert(logPosts(rt) === 0, 'no POST');
  });

  await check('DIARY: double confirm tap saves once (same idempotency key)', async () => {
    const rt = makeRuntime({ tts: true });
    const p = await openPage(ws, DIARY, rt);
    await p.call('handleText', `${y.m}월 ${y.d}일 간식 바나나 하나 기록`);
    assert(p.data().view === 'confirm', 'confirm');
    await Promise.all([p.call('saveLog'), p.call('saveLog')]);
    const snacks = (await backend.api('/api/v1/meal-logs?date=' + y.iso + '&meal_type=snack')).items;
    assert(snacks.length === 1, 'one snack log, got ' + snacks.length);
  });
}
