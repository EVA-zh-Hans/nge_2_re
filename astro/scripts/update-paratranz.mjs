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

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  updateData().catch(error => {
    console.error(`ParaTranz data update failed: ${error.message}`);
    process.exitCode = 1;
  });
}
