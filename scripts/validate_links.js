const fs = require('fs');
const path = require('path');

function validateFile(readmePath, baseDir) {
  const content = fs.readFileSync(readmePath, 'utf8');
  const regex = /!\[([^\]]*)\]\(([^)]+)\)/g;
  let match;
  let allOk = true;
  console.log('Validating:', readmePath);
  while ((match = regex.exec(content)) !== null) {
    const link = match[2];
    const resolved = path.resolve(baseDir, link);
    const exists = fs.existsSync(resolved);
    console.log(`  [${exists ? 'OK' : 'MISSING'}] ${link} -> ${resolved}`);
    if (!exists) allOk = false;
  }
  return allOk;
}

const rootOk = validateFile('D:/PROJECTS/FLOWPILOT-AI/README.md', 'D:/PROJECTS/FLOWPILOT-AI');
const feOk = validateFile('D:/PROJECTS/FLOWPILOT-AI/frontend/README.md', 'D:/PROJECTS/FLOWPILOT-AI/frontend');

if (rootOk && feOk) {
  console.log('\nSUCCESS: ALL REFERENCED IMAGES EXIST AND RESOLVE CORRECTLY!');
  process.exit(0);
} else {
  console.error('\nERROR: ONE OR MORE IMAGES ARE MISSING!');
  process.exit(1);
}
