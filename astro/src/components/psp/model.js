import * as THREE from 'three';

// Local, procedural PSP geometry: no remote model or texture requests.
export function createPsp(screenTexture) {
  const model = new THREE.Group();
  const shell = new THREE.MeshStandardMaterial({ color: 0x17191e, metalness: 0.32, roughness: 0.3 });
  const back = new THREE.MeshStandardMaterial({ color: 0x202126, metalness: 0.18, roughness: 0.48 });
  const chrome = new THREE.MeshStandardMaterial({ color: 0x8b8e96, metalness: 0.72, roughness: 0.28 });
  const black = new THREE.MeshStandardMaterial({ color: 0x08090c, roughness: 0.25 });
  const button = new THREE.MeshStandardMaterial({ color: 0x252730, metalness: 0.28, roughness: 0.32 });

  function rounded(w, h, r) {
    const s = new THREE.Shape();
    s.moveTo(-w / 2 + r, -h / 2);
    s.lineTo(w / 2 - r, -h / 2);
    s.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r);
    s.lineTo(w / 2, h / 2 - r);
    s.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2);
    s.lineTo(-w / 2 + r, h / 2);
    s.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r);
    s.lineTo(-w / 2, -h / 2 + r);
    s.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2);
    return s;
  }

  function plate(w, h, r, depth, material, x = 0, y = 0, z = 0, bevel = 0.035) {
    const geometry = new THREE.ExtrudeGeometry(rounded(w, h, r), {
      depth, bevelEnabled: true, bevelSegments: 3, steps: 1,
      bevelSize: bevel, bevelThickness: bevel, curveSegments: 12,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(x, y, z);
    model.add(mesh);
    return mesh;
  }

  function disc(radius, depth, material, x, y, z) {
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, depth, 40), material);
    mesh.rotation.x = Math.PI / 2;
    mesh.position.set(x, y, z);
    model.add(mesh);
    return mesh;
  }

  function label(text, x, y, z, width, height, color = '#c3c6cf', font = '500 48px Arial') {
    const canvas = document.createElement('canvas');
    canvas.width = Math.ceil(256 * width / height);
    canvas.height = 256;
    const ctx = canvas.getContext('2d');
    ctx.font = font.replace(/\d+px/, '180px');
    ctx.fillStyle = color;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, canvas.width / 2, 128, canvas.width * .9);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(width, height), new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false }));
    mesh.position.set(x, y, z);
    model.add(mesh);
    return mesh;
  }

  plate(7.9, 3.42, 1.02, .16, back, 0, 0, -.24, .1);
  plate(7.94, 3.43, 1.02, .055, chrome, 0, 0, -.06, .045);
  plate(7.9, 3.4, 1.02, .17, shell, 0, 0, 0, .09);
  // Shoulder buttons and the recessed display surround.
  plate(1.05, .17, .08, .2, chrome, -2.85, 1.61, -.14);
  plate(1.05, .17, .08, .2, chrome, 2.85, 1.61, -.14);
  plate(5.08, 2.97, .17, .025, black, 0, .04, .265);
  plate(4.7, 2.67, .04, .012, chrome, 0, .04, .298, .012);
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(4.61, 4.61 * 272 / 480), new THREE.MeshBasicMaterial({ map: screenTexture, toneMapped: false }));
  screen.position.set(0, .04, .326);
  model.add(screen);
  // A restrained glass highlight keeps the screenshot readable.
  const glassCanvas = document.createElement('canvas');
  glassCanvas.width = 128; glassCanvas.height = 128;
  const glassCtx = glassCanvas.getContext('2d');
  const sheen = glassCtx.createLinearGradient(0, 0, 100, 128);
  sheen.addColorStop(0, '#ffffff25'); sheen.addColorStop(.5, '#ffffff00'); sheen.addColorStop(1, '#ffffff08');
  glassCtx.fillStyle = sheen; glassCtx.fillRect(0, 0, 128, 128);
  const glass = new THREE.Mesh(new THREE.PlaneGeometry(4.61, 4.61 * 272 / 480), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(glassCanvas), transparent: true, depthWrite: false }));
  glass.position.copy(screen.position); glass.position.z += .005; model.add(glass);

  // Four separate direction buttons, with a recessed centre.
  disc(.57, .04, black, -3.12, .38, .275);
  for (let i = 0; i < 4; i++) {
    const angle = i * Math.PI / 2;
    const x = -3.12 + Math.sin(angle) * .3;
    const y = .38 + Math.cos(angle) * .3;
    const key = plate(.27, .4, .04, .09, button, x, y, .3, .035);
    key.rotation.z = -angle;
    const mark = label('▴', x, y, .441, .18, .13, '#a1a4ae');
    mark.rotation.z = -angle;
  }
  const symbols = ['△', '○', '×', '□'];
  const colors = ['#7ec6b0', '#e49caa', '#9daee6', '#d5a3d0'];
  for (let i = 0; i < 4; i++) {
    const angle = i * Math.PI / 2;
    const x = 3.13 + Math.sin(angle) * .39;
    const y = .34 + Math.cos(angle) * .39;
    disc(.235, .055, chrome, x, y, .3);
    disc(.216, .105, button, x, y, .35);
    label(symbols[i], x, y, .412, .53, .35, colors[i], '500 82px Arial');
  }
  disc(.35, .095, black, -3.12, -.8, .32);
  disc(.3, .065, button, -3.12, -.8, .4);
  // Concentric grip ridges on the analog nub.
  for (let r = .07; r < .29; r += .047) {
    const ridge = new THREE.Mesh(new THREE.TorusGeometry(r, .009, 5, 36), back);
    ridge.position.set(-3.12, -.8, .438); model.add(ridge);
  }
  for (const x of [-2.74, 2.74]) {
    for (let i = 0; i < 4; i++) plate(.045, .13, .02, .006, black, x + i * .072, -.84, .287, .005);
  }
  label('SONY', -2.98, 1.19, .28, .58, .16, '#e0e1e8', 'bold 55px Georgia');
  label('PSP', 0, -1.49, .293, .79, .24, '#ccd0d9', 'italic 65px Arial');
  label('POWER', 3.16, -.98, .288, .49, .09);
  disc(.033, .012, new THREE.MeshBasicMaterial({ color: 0xa2ec6c }), 3.49, -.98, .293);
  label('HOLD', 3.16, -1.16, .288, .39, .08, '#858a93');
  for (const [text, x, w] of [['HOME', -2.23, .38], ['−', -1.62, .17], ['+', -1.3, .17], ['SELECT', 1.64, .41], ['START', 2.2, .38]]) {
    plate(w, .12, .055, .025, button, x, -1.48, .28, .01);
    label(text, x, -1.48, .32, w * .9, .075, '#c0c2cb');
  }
  // The UMD door remains real geometry as the device tilts.
  const umd = new THREE.Mesh(new THREE.TorusGeometry(1.12, .025, 8, 72), chrome);
  umd.position.z = -.35; model.add(umd);
  const rearLogo = label('PSP', 0, 0, -.365, 1.15, .3);
  rearLogo.rotation.y = Math.PI;
  return model;
}
