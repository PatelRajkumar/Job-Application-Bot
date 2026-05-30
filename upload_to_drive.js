// upload_to_drive.js
// Usage: node upload_to_drive.js <file1> [file2] [file3]
// Setup: node upload_to_drive.js --setup

const { google } = require('googleapis');
const fs = require('fs');
const path = require('path');
const http = require('http');
const url = require('url');

// ─── Config ────────────────────────────────────────────────────────────────
const CREDENTIALS_FILE = path.join(__dirname, 'credentials.json');
const TOKEN_FILE = path.join(__dirname, 'token.json');
const SCOPES = ['https://www.googleapis.com/auth/drive.file'];

// Environment variables (used in production/Render)
const ENV_CLIENT_ID = process.env.GOOGLE_CLIENT_ID;
const ENV_CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET;
const ENV_REFRESH_TOKEN = process.env.GOOGLE_REFRESH_TOKEN;
const DRIVE_FOLDER_ID = process.env.DRIVE_FOLDER_ID || null;

// ─── Auth ───────────────────────────────────────────────────────────────────
function getOAuth2Client() {
  // Try env vars first (for Render / production)
  if (ENV_CLIENT_ID && ENV_CLIENT_SECRET && ENV_REFRESH_TOKEN) {
    const auth = new google.auth.OAuth2(ENV_CLIENT_ID, ENV_CLIENT_SECRET);
    auth.setCredentials({ refresh_token: ENV_REFRESH_TOKEN });
    return auth;
  }

  // Fallback: local credentials.json + token.json
  if (!fs.existsSync(CREDENTIALS_FILE)) {
    console.error('❌ credentials.json not found and no env vars set.');
    console.error('   Run: node upload_to_drive.js --setup');
    process.exit(1);
  }
  const { client_id, client_secret, redirect_uris } = JSON.parse(
    fs.readFileSync(CREDENTIALS_FILE)
  ).installed;
  const auth = new google.auth.OAuth2(client_id, client_secret, redirect_uris[0]);

  if (fs.existsSync(TOKEN_FILE)) {
    auth.setCredentials(JSON.parse(fs.readFileSync(TOKEN_FILE)));
  }
  return auth;
}

// ─── One-Time Setup ─────────────────────────────────────────────────────────
async function runSetup() {
  if (!fs.existsSync(CREDENTIALS_FILE)) {
    console.error('❌ credentials.json not found.');
    console.error('   Download it from Google Cloud Console → APIs & Services → Credentials');
    console.error('   Place it at: ' + CREDENTIALS_FILE);
    process.exit(1);
  }

  const { client_id, client_secret, redirect_uris } = JSON.parse(
    fs.readFileSync(CREDENTIALS_FILE)
  ).installed;

  const auth = new google.auth.OAuth2(client_id, client_secret, 'http://localhost');
  const authUrl = auth.generateAuthUrl({ access_type: 'offline', scope: SCOPES, prompt: 'consent' });

  console.log('\n🔑 Google Drive OAuth Setup\n');
  console.log('Opening browser for authorization...');
  console.log('If it does not open, visit this URL:\n');
  console.log(authUrl + '\n');

  // Try to open browser
  const { exec } = require('child_process');
  exec(`start "" "${authUrl}"`);

  // Start local server to catch the callback
  // Use port 80 to match redirect_uri 'http://localhost'
  await new Promise((resolve, reject) => {
    const server = http.createServer(async (req, res) => {
      res.setHeader('Access-Control-Allow-Origin', '*');
      const parsed = url.parse(req.url || '/', true);
      if (parsed.query.code) {
        try {
          const { tokens } = await auth.getToken(parsed.query.code);
          auth.setCredentials(tokens);
          fs.writeFileSync(TOKEN_FILE, JSON.stringify(tokens, null, 2));

          res.writeHead(200, { 'Content-Type': 'text/html' });
          res.end('<h2>✅ Authorization successful! You can close this tab.</h2>');

          console.log('\n✅ token.json saved successfully!');
          console.log('\n📋 For Render.com, set these environment variables:');
          console.log(`   GOOGLE_CLIENT_ID=${client_id}`);
          console.log(`   GOOGLE_CLIENT_SECRET=${client_secret}`);
          console.log(`   GOOGLE_REFRESH_TOKEN=${tokens.refresh_token}`);
          console.log('\n📁 Also set:');
          console.log('   DRIVE_FOLDER_ID=<your Google Drive folder ID from the URL>');

          server.close();
          resolve();
        } catch (err) {
          res.writeHead(500);
          res.end('Error: ' + err.message);
          reject(err);
        }
      }
    });
    const port = 80;
    server.listen(port, () => console.log(`⏳ Waiting for authorization callback on http://localhost ...`));
    server.on('error', reject);
  });
}

// ─── Subfolder ───────────────────────────────────────────────────────────────
/**
 * Creates a subfolder inside parentFolderId (or Drive root if null).
 * If a folder with the same name already exists, returns its existing ID
 * so we never get duplicate folders for the same company.
 */
async function getOrCreateSubfolder(auth, folderName, parentFolderId) {
  const drive = google.drive({ version: 'v3', auth });

  // Search for existing folder with this name under the parent
  const q = [
    `name = '${folderName.replace(/'/g, "\\'")}'`,
    `mimeType = 'application/vnd.google-apps.folder'`,
    `trashed = false`,
    ...(parentFolderId ? [`'${parentFolderId}' in parents`] : []),
  ].join(' and ');

  const existing = await drive.files.list({
    q,
    fields: 'files(id, name, webViewLink)',
    spaces: 'drive',
  });

  if (existing.data.files.length > 0) {
    const folder = existing.data.files[0];
    console.log(`📁 Using existing folder: ${folderName} (${folder.id})`);
    return folder.id;
  }

  // Create new subfolder
  const metadata = {
    name: folderName,
    mimeType: 'application/vnd.google-apps.folder',
    ...(parentFolderId ? { parents: [parentFolderId] } : {}),
  };

  const created = await drive.files.create({
    resource: metadata,
    fields: 'id, name',
  });

  // Make subfolder link-shareable so the bot can send a folder link too
  await drive.permissions.create({
    fileId: created.data.id,
    resource: { role: 'reader', type: 'anyone' },
  });

  console.log(`📁 Created subfolder: ${folderName} (${created.data.id})`);
  return created.data.id;
}

// ─── Versioning & Cleanup ───────────────────────────────────────────────────
async function getOrCreateVersionFolder(auth, companyFolderId) {
  const drive = google.drive({ version: 'v3', auth });

  // List all items in the company folder
  const res = await drive.files.list({
    q: `'${companyFolderId}' in parents and trashed = false`,
    fields: 'files(id, name, mimeType)',
  });
  const items = res.data.files;

  const folders = items.filter(f => f.mimeType === 'application/vnd.google-apps.folder');
  const looseFiles = items.filter(f => f.mimeType !== 'application/vnd.google-apps.folder');

  // Determine highest existing version
  let maxV = 0;
  folders.forEach(f => {
    const match = f.name.match(/^v(\d+)_/i);
    if (match) {
      maxV = Math.max(maxV, parseInt(match[1], 10));
    }
  });

  // If there are loose files, move them to a legacy folder
  if (looseFiles.length > 0) {
    maxV++;
    const legacyName = `v${maxV}_Legacy`;
    console.log(`🧹 Found ${looseFiles.length} loose files. Moving them to ${legacyName}...`);

    const legacyFolder = await drive.files.create({
      resource: { name: legacyName, mimeType: 'application/vnd.google-apps.folder', parents: [companyFolderId] },
      fields: 'id',
    });

    for (const f of looseFiles) {
      await drive.files.update({
        fileId: f.id,
        addParents: legacyFolder.data.id,
        removeParents: companyFolderId,
        fields: 'id, parents'
      });
    }
  }

  // Create the new version folder
  maxV++;
  const now = new Date();
  const pad = (n) => n.toString().padStart(2, '0');
  const dateStr = `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())}_${pad(now.getHours())}-${pad(now.getMinutes())}`;
  const newFolderName = `v${maxV}_${dateStr}`;

  console.log(`📁 Creating new version folder: ${newFolderName}`);
  const newFolder = await drive.files.create({
    resource: { name: newFolderName, mimeType: 'application/vnd.google-apps.folder', parents: [companyFolderId] },
    fields: 'id',
  });

  // Make it readable
  await drive.permissions.create({
    fileId: newFolder.data.id,
    resource: { role: 'reader', type: 'anyone' },
  });

  return newFolder.data.id;
}

// ─── Upload ──────────────────────────────────────────────────────────────────
async function uploadFile(auth, filePath, folderId) {
  const drive = google.drive({ version: 'v3', auth });
  const fileName = path.basename(filePath);
  const mimeType = getMimeType(filePath);

  console.log(`📤 Uploading: ${fileName}`);

  const fileMetadata = {
    name: fileName,
    ...(folderId ? { parents: [folderId] } : {}),
  };

  const media = {
    mimeType,
    body: fs.createReadStream(filePath),
  };

  const response = await drive.files.create({
    resource: fileMetadata,
    media,
    fields: 'id, name, webViewLink, webContentLink',
  });

  // Make it readable by anyone with link
  await drive.permissions.create({
    fileId: response.data.id,
    resource: { role: 'reader', type: 'anyone' },
  });

  console.log(`✅ Uploaded: ${fileName}`);
  console.log(`   🔗 ${response.data.webViewLink}`);

  return {
    name: fileName,
    id: response.data.id,
    viewLink: response.data.webViewLink,
    downloadLink: response.data.webContentLink,
  };
}

function getMimeType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const types = {
    '.pdf': 'application/pdf',
    '.html': 'text/html',
    '.md': 'text/markdown',
    '.txt': 'text/plain',
  };
  return types[ext] || 'application/octet-stream';
}

// ─── Main ────────────────────────────────────────────────────────────────────
async function main() {
  const args = process.argv.slice(2);

  if (args[0] === '--setup') {
    await runSetup();
    return;
  }

  if (args.length === 0) {
    console.log('Usage:  node upload_to_drive.js [--folder <CompanyName>] <file1> [file2] ...');
    console.log('        node upload_to_drive.js --folder AlignTechnology resume.pdf guide.md');
    console.log('Setup:  node upload_to_drive.js --setup');
    process.exit(0);
  }

  // Parse optional --folder <name> flag
  let subfolderName = null;
  let fileArgs = args;
  if (args[0] === '--folder' && args[1]) {
    subfolderName = args[1];
    fileArgs = args.slice(2);
  }

  if (fileArgs.length === 0) {
    console.error('❌ No files specified.');
    process.exit(1);
  }

  // Validate all files exist
  for (const filePath of fileArgs) {
    if (!fs.existsSync(filePath)) {
      console.error(`❌ File not found: ${filePath}`);
      process.exit(1);
    }
  }

  const auth = getOAuth2Client();

  // Determine target folder: create/find subfolder if --folder was given
  let targetFolderId = DRIVE_FOLDER_ID || null;
  let folderViewLink = null;
  if (subfolderName) {
    const companyFolderId = await getOrCreateSubfolder(auth, subfolderName, targetFolderId);
    
    // Automatically manage versioning and cleanup loose files
    targetFolderId = await getOrCreateVersionFolder(auth, companyFolderId);
    
    // Build a folder view link for the specific version folder
    folderViewLink = `https://drive.google.com/drive/folders/${targetFolderId}`;
    console.log(`📂 Uploading into version folder...`);
    console.log(`   🔗 ${folderViewLink}`);
  }

  const results = [];
  for (const filePath of fileArgs) {
    try {
      const result = await uploadFile(auth, filePath, targetFolderId);
      results.push(result);
    } catch (err) {
      console.error(`❌ Failed to upload ${path.basename(filePath)}: ${err.message}`);
      results.push({ name: path.basename(filePath), error: err.message });
    }
  }

  // Output JSON for consumption by the bot (includes optional folderLink)
  const output = { files: results };
  if (folderViewLink) output.folderLink = folderViewLink;
  console.log('\n📦 UPLOAD_RESULTS_JSON:' + JSON.stringify(output));
}

main().catch(err => {
  console.error('❌ Fatal error:', err.message);
  process.exit(1);
});
