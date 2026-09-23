import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { validateFiles, validateLeaderboard, updateData } from './update-paratranz.mjs';

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
