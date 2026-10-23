// Refresh status: node scripts/update-paratranz.mjs
// Refresh public history: node scripts/update-paratranz.mjs --history
import { writeFile, rename } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const dataDirectory = new URL('../src/data/', import.meta.url);

export function validateFiles(files) {
  if (!Array.isArray(files) || files.length === 0) {
    throw new Error('ParaTranz must return a non-empty file list');
  }
  const ids = new Set();
  for (const file of files) {
    if (!file || !Number.isSafeInteger(file.id) || ids.has(file.id)
      || typeof file.name !== 'string' || !file.name
      || typeof file.folder !== 'string') {
      throw new Error('Invalid or duplicate ParaTranz file');
    }
    ids.add(file.id);
    for (const field of ['total', 'translated', 'disputed', 'checked', 'reviewed']) {
      if (!Number.isSafeInteger(file[field]) || file[field] < 0
        || (field !== 'total' && file[field] > file.total)) {
        throw new Error(`Invalid ${field} for ParaTranz file ${file.id}`);
      }
    }
  }
  return files;
}

export function validateLeaderboard(users) {
  if (!Array.isArray(users)) throw new Error('ParaTranz must return a leaderboard array');
  const ids = new Set();
  for (const user of users) {
    if (!user || !Number.isSafeInteger(user.id) || ids.has(user.id)
      || typeof user.username !== 'string' || !user.username
      || (user.nickname != null && typeof user.nickname !== 'string')) {
      throw new Error('Invalid or duplicate ParaTranz contributor');
    }
    ids.add(user.id);
    for (const field of ['translated', 'edited', 'reviewed']) {
      if (!Number.isSafeInteger(user[field]) || user[field] < 0) {
        throw new Error(`Invalid ${field} for ParaTranz contributor ${user.id}`);
      }
    }
    if (!Number.isFinite(user.points) || user.points < 0) {
      throw new Error(`Invalid points for ParaTranz contributor ${user.id}`);
    }
  }
  return users;
}

async function fetchData(resource, validate, fetcher) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const response = await fetcher(`https://paratranz.cn/api/projects/10882/${resource}`, {
        headers: { Accept: 'application/json' },
        signal: AbortSignal.timeout(30_000),
      });
      if (!response.ok) throw new Error(`ParaTranz HTTP ${response.status}`);
      return validate(await response.json());
    } catch (error) {
      if (attempt === 3) throw error;
      console.warn(`ParaTranz ${resource} attempt ${attempt} failed; retrying: ${error.message}`);
      await new Promise(resolve => setTimeout(resolve, attempt * 2000));
    }
  }
}

export async function updateData(fetcher = fetch, directory = dataDirectory) {
  // Validate both responses before replacing either snapshot.
  const files = await fetchData('files', validateFiles, fetcher);
  const leaderboard = await fetchData('leaderboard', validateLeaderboard, fetcher);
  for (const [name, data] of [['files', files], ['leaderboard', leaderboard]]) {
    const temporary = new URL(`${name}.json.tmp`, directory);
    await writeFile(temporary, JSON.stringify(data, null, 2) + '\n');
    await rename(temporary, new URL(`${name}.json`, directory));
  }
  console.log(`Updated ${files.length} ParaTranz files and ${leaderboard.length} contributors.`);
}

// History is an explicit, separate snapshot: the regular status refresh stays small.
export async function updateHistory(fetcher = fetch, directory = dataDirectory) {
  const users = new Map();
  const records = new Map();
  let pages = 1;
  let expected = 0;
  for (let page = 1; page <= pages; page++) {
    const data = await fetchData(`history?page=${page}&pageSize=1000`, value => {
      if (!Array.isArray(value.results) || !Number.isSafeInteger(value.pageCount)
        || !Number.isSafeInteger(value.rowCount) || value.pageCount < 1 || value.pageCount > 1000) {
        throw new Error('Invalid ParaTranz history page');
      }
      return value;
    }, fetcher);
    if (page === 1) { pages = data.pageCount; expected = data.rowCount; }
    for (const item of data.results) {
      const time = Date.parse(item.createdAt);
      if (!Number.isSafeInteger(item.id) || !Number.isFinite(time)
        || !Number.isSafeInteger(item.uid) || typeof item.operation !== 'string') {
        throw new Error('Invalid ParaTranz history event');
      }
      const user = item.user || {};
      const name = user.nickname?.trim() || user.username || `uid:${item.uid}`;
      let avatar = user.avatar || '';
      if (avatar.startsWith('/media/')) avatar = `https://paratranz.cn${avatar}`;
      if (!avatar.startsWith('https://')) avatar = '';
      users.set(item.uid, { id: item.uid, name, avatar });
      // Excerpts are display-only; never represent them as full translation exports.
      const excerpt = value => String(value ?? '').slice(0, 240);
      records.set(item.id, [item.id, time, item.uid, item.tid || 0,
        item.operation, item.field || '', excerpt(item.from), excerpt(item.to),
        excerpt(item.target?.original)]);
    }
    console.log(`History ${page}/${pages}: ${records.size} records`);
  }
  if (records.size !== expected) {
    throw new Error(`History changed during download (${records.size}/${expected}); retry for a consistent snapshot`);
  }
  const events = [...records.values()].sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  const snapshot = { project: 10882, fetchedAt: new Date().toISOString(),
    source: 'https://paratranz.cn/api/projects/10882/history',
    excerptLimit: 240, count: events.length, users: [...users.values()], events };
  const temporary = new URL('history.json.tmp', directory);
  await writeFile(temporary, JSON.stringify(snapshot) + '\n');
  await rename(temporary, new URL('history.json', directory));
  console.log(`Saved ${events.length} real operations by ${users.size} contributors.`);
  return snapshot;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  (process.argv.includes('--history') ? updateHistory() : updateData()).catch(error => {
    console.error(`ParaTranz data update failed: ${error.message}`);
    process.exitCode = 1;
  });
}
