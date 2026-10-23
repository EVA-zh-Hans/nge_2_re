import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { validateFiles, validateLeaderboard, updateData, updateHistory } from './update-paratranz.mjs';

const snapshot = JSON.parse(await readFile(new URL('../src/data/files.json', import.meta.url)));
const leaderboard = JSON.parse(await readFile(new URL('../src/data/leaderboard.json', import.meta.url)));

test('accepts contributor snapshots, fractional points and an empty leaderboard', () => {
  assert.equal(validateLeaderboard(leaderboard), leaderboard);
  assert.deepEqual(validateLeaderboard([]), []);
});

test('rejects malformed contributors and duplicate identities', () => {
  for (const input of [null, { error: 'Unauthorized' }, [leaderboard[0], leaderboard[0]]]) {
    assert.throws(() => validateLeaderboard(input));
  }
  for (const change of [
    { username: null }, { nickname: {} }, { edited: undefined },
    { translated: -1 }, { reviewed: '2' }, { points: NaN },
  ]) {
    assert.throws(() => validateLeaderboard([{ ...leaderboard[0], ...change }]));
  }
});

test('fetches both endpoints and saves both snapshots', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'nge-paratranz-'));
  const requests = [];
  try {
    await updateData(async url => {
      requests.push(url);
      return { ok: true, json: async () => url.endsWith('/files') ? snapshot : leaderboard };
    }, pathToFileURL(directory + '/'));
    assert.deepEqual(requests, [
      'https://paratranz.cn/api/projects/10882/files',
      'https://paratranz.cn/api/projects/10882/leaderboard',
    ]);
    assert.deepEqual(JSON.parse(await readFile(join(directory, 'files.json'))), snapshot);
    assert.deepEqual(JSON.parse(await readFile(join(directory, 'leaderboard.json'))), leaderboard);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test('accepts the existing ParaTranz snapshot', () => {
  assert.equal(validateFiles(snapshot), snapshot);
});

test('rejects error responses, empty results and duplicate files', () => {
  for (const input of [{ error: 'Unauthorized' }, [], null, [snapshot[0], snapshot[0]]]) {
    assert.throws(() => validateFiles(input));
  }
});

test('rejects missing fields and invalid statistics before replacement', () => {
  for (const change of [
    { folder: null }, { name: '' }, { checked: undefined },
    { total: -1 }, { translated: '1' }, { reviewed: 0.5 },
    { checked: snapshot[0].total + 1 },
  ]) {
    assert.throws(() => validateFiles([{ ...snapshot[0], ...change }]));
  }
});

const historyEvent = (id, createdAt) => ({
  id, createdAt, uid: 52522, tid: 10, operation: 'edit', field: 'translation',
  from: '旧译文', to: '新译文', target: { original: '原文' },
  user: { nickname: 'main_void', username: 'xeonliu', avatar: '/media/avatar.png' },
});

test('history snapshot paginates, sorts chronologically and retains real identities and changes', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'nge-history-'));
  const requests = [];
  try {
    const result = await updateHistory(async url => {
      requests.push(url);
      const page = new URL(url).searchParams.get('page');
      return { ok: true, json: async () => ({ pageCount: 2, rowCount: 2,
        results: [historyEvent(Number(page), page === '1' ? '2026-01-01Z' : '2024-07-09Z')] }) };
    }, pathToFileURL(directory + '/'));
    assert.equal(requests.length, 2);
    assert.equal(result.events[0][0], 2);
    assert.deepEqual(result.events[0].slice(2), [52522, 10, 'edit', 'translation', '旧译文', '新译文', '原文']);
    assert.deepEqual(result.users, [{ id: 52522, name: 'main_void', avatar: 'https://paratranz.cn/media/avatar.png' }]);
    assert.deepEqual(JSON.parse(await readFile(join(directory, 'history.json'))), result);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test('inconsistent history cannot replace an existing snapshot', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'nge-history-'));
  const { writeFile } = await import('node:fs/promises');
  try {
    await writeFile(join(directory, 'history.json'), 'previous snapshot');
    await assert.rejects(updateHistory(async () => ({ ok: true, json: async () => ({
      pageCount: 2, rowCount: 2, results: [historyEvent(1, '2026-01-01Z')],
    }) }), pathToFileURL(directory + '/')), /changed during download/);
    assert.equal(await readFile(join(directory, 'history.json'), 'utf8'), 'previous snapshot');
  } finally { await rm(directory, { recursive: true, force: true }); }
});
