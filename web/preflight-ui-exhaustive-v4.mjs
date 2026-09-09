import fs from 'node:fs';
const source=fs.readFileSync('preflight-ui-exhaustive-v3.mjs','utf8');
const fixed=source.replace("if(!(await el.isVisible()).catch(()=>false))continue;if((await el.isDisabled().catch(()=>false)))continue;","if(!(await el.isVisible()))continue;if(await el.isDisabled())continue;");
if(fixed===source)throw new Error('Expected harness patch target was not found');
fs.writeFileSync('preflight-ui-exhaustive-v3-fixed.mjs',fixed);
await import('./preflight-ui-exhaustive-v3-fixed.mjs');
