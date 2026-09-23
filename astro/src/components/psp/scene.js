import * as THREE from 'three';
import { createPsp } from './model.js';

export async function initPspHero(hero) {
  const stage = hero.querySelector('[data-psp-stage]');
  const motionButton = hero.querySelector('.psp-hero__motion');
  const scrollLabel = hero.querySelector('.psp-hero__scroll-label');
  const copy = hero.querySelector('.psp-hero__copy');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const mobile = window.matchMedia('(max-width: 760px)');
  let renderer;
  let model;
  let screenTexture;
  let disposed = false;
  let frame = 0;
  let visible = true;
  let paused = false;
  let progress = 0;
  let target = 0;
  let pointerX = 0;
  let pointerY = 0;
  let currentX = 0;
  let currentY = 0;
  let lastTime = 0;
  let scene;
  let observer;
  let resizeObserver;
  const camera = new THREE.PerspectiveCamera(33, 1, .1, 100);
  const cleanups = [];
  const staticMode = () => paused || reducedMotion.matches;
  const clamp = (n) => Math.max(0, Math.min(1, n));
  const smooth = (n) => n * n * (3 - 2 * n);

  function listen(element, event, handler, options) {
    element.addEventListener(event, handler, options);
    cleanups.push(() => element.removeEventListener(event, handler, options));
  }
  function dispose() {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(frame);
    observer?.disconnect(); resizeObserver?.disconnect();
    cleanups.forEach((cleanup) => cleanup());
    const geometries = new Set();
    const materials = new Set();
    const textures = new Set([screenTexture]);
    scene?.traverse((object) => {
      if (object.geometry) geometries.add(object.geometry);
      if (object.material) {
        for (const material of [object.material].flat()) {
          materials.add(material);
          if (material.map) textures.add(material.map);
        }
      }
    });
    geometries.forEach((geometry) => geometry.dispose());
    materials.forEach((material) => material.dispose());
    textures.forEach((texture) => texture?.dispose());
    renderer?.dispose(); renderer?.domElement.remove();
  }
  function fallback() {
    dispose();
    hero.classList.remove('is-ready', 'is-static');
    hero.style.setProperty('--copy-opacity', '1');
    hero.style.setProperty('--caption-opacity', '0');
    copy.inert = false;
    copy.removeAttribute('aria-hidden');
    motionButton.hidden = true;
    scrollLabel.textContent = '探索汉化计划';
  }
  function requestFrame() {
    if (!disposed && visible && !document.hidden && !frame) frame = requestAnimationFrame(render);
  }
  function updateTarget() {
    const rect = hero.getBoundingClientRect();
    const distance = hero.offsetHeight - hero.querySelector('.psp-hero__sticky').offsetHeight;
    target = reducedMotion.matches ? 0 : paused ? progress : clamp(-rect.top / Math.max(1, distance));
    requestFrame();
  }
  function resize() {
    const { width, height } = stage.getBoundingClientRect();
    if (!width || !height) return;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
    renderer.setSize(width, height);
    camera.aspect = width / height;
    // Fit the full console on narrow screens; reserve the left side for the heading on desktop.
    const viewWidth = mobile.matches ? 10.3 : Math.max(15.7, 9 * camera.aspect);
    camera.position.z = viewWidth / (2 * Math.tan(THREE.MathUtils.degToRad(16.5)) * camera.aspect);
    camera.updateProjectionMatrix();
    updateTarget();
  }
  function render(time) {
    frame = 0;
    if (disposed) return;
    const dt = Math.min((time - (lastTime || time - 16)) / 1000, .05);
    lastTime = time;
    const blend = 1 - Math.exp(-dt * 11);
    progress = reducedMotion.matches ? 0 : THREE.MathUtils.lerp(progress, target, blend);
    currentX = staticMode() ? 0 : THREE.MathUtils.lerp(currentX, pointerX, blend);
    currentY = staticMode() ? 0 : THREE.MathUtils.lerp(currentY, pointerY, blend);
    const approach = smooth(progress);
    // The first half turns the face toward the viewer; the second half pushes it forward.
    const turn = smooth(clamp(progress * 1.65));
    model.rotation.set(
      THREE.MathUtils.lerp(.23, -.1, turn) + currentY * .035,
      THREE.MathUtils.lerp(-.38, .16, turn) + currentX * .06,
      THREE.MathUtils.lerp(-.16, .075, approach),
    );
    model.position.set(mobile.matches ? 0 : 2.95 * (1 - approach), mobile.matches ? .2 + approach * .8 : approach * .75, camera.position.z * (mobile.matches ? .08 : .22) * approach);
    model.scale.setScalar(1 + approach * (mobile.matches ? .02 : .16));
    const opacity = 1 - smooth(clamp(progress / .35));
    hero.style.setProperty('--progress', progress.toFixed(4));
    hero.style.setProperty('--copy-opacity', opacity.toFixed(4));
    hero.style.setProperty('--caption-opacity', smooth(clamp((progress - .58) / .3)).toFixed(4));
    copy.inert = opacity < .05;
    copy.setAttribute('aria-hidden', String(opacity < .05));
    renderer.render(scene, camera);
    if (Math.abs(progress - target) > .0001 || Math.abs(currentX - pointerX) > .001 || Math.abs(currentY - pointerY) > .001) requestFrame();
  }
  function syncMotion() {
    hero.classList.toggle('is-static', reducedMotion.matches);
    pointerX = 0; pointerY = 0;
    motionButton.setAttribute('aria-pressed', String(staticMode()));
    motionButton.textContent = staticMode() ? '动态效果已关闭' : '暂停动态效果';
    // Honor the system preference; the toggle stays available when motion is permitted.
    motionButton.hidden = reducedMotion.matches;
    if (paused && !reducedMotion.matches) motionButton.textContent = '开启动态效果';
    scrollLabel.textContent = staticMode() ? '探索汉化计划' : '向下滚动，进入世界';
    resize();
  }

  try {
    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'low-power' });
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setClearColor(0x000000, 0);
    renderer.domElement.setAttribute('aria-hidden', 'true');
    stage.append(renderer.domElement);
    listen(renderer.domElement, 'webglcontextlost', (event) => { event.preventDefault(); fallback(); });
    screenTexture = await new THREE.TextureLoader().loadAsync(stage.dataset.screen);
    if (disposed || !hero.isConnected) { screenTexture.dispose(); dispose(); return; }
    screenTexture.colorSpace = THREE.SRGBColorSpace;
    screenTexture.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
    scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xece9ff, 0x777084, 3.3));
    const key = new THREE.DirectionalLight(0xffffff, 4.5);
    key.position.set(-4, 7, 7); scene.add(key);
    const rim = new THREE.DirectionalLight(0xc5b0ef, 3);
    rim.position.set(4, 2, -3); scene.add(rim);
    const fill = new THREE.DirectionalLight(0xe1f2d1, 1.7);
    fill.position.set(2, -3, 5); scene.add(fill);
    model = createPsp(screenTexture);
    scene.add(model);
    // Soft contact shadow rendered in the same 3D scene.
    const shadowCanvas = document.createElement('canvas');
    shadowCanvas.width = 128; shadowCanvas.height = 128;
    const ctx = shadowCanvas.getContext('2d');
    const gradient = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    gradient.addColorStop(0, '#42325028'); gradient.addColorStop(1, '#42325000');
    ctx.fillStyle = gradient; ctx.fillRect(0, 0, 128, 128);
    const shadow = new THREE.Mesh(new THREE.PlaneGeometry(8, 2.2), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(shadowCanvas), transparent: true, depthWrite: false }));
    shadow.position.set(0, -2.25, -.7); model.add(shadow);
    hero.classList.add('is-ready');
    syncMotion();
    listen(window, 'scroll', updateTarget, { passive: true });
    listen(reducedMotion, 'change', syncMotion);
    listen(mobile, 'change', resize);
    listen(motionButton, 'click', () => { paused = !paused; syncMotion(); });
    listen(hero, 'pointermove', (event) => {
      if (staticMode() || event.pointerType !== 'mouse') return;
      const rect = hero.querySelector('.psp-hero__sticky').getBoundingClientRect();
      pointerX = (event.clientX - rect.left) / rect.width - .5;
      pointerY = (event.clientY - rect.top) / rect.height - .5;
      requestFrame();
    });
    listen(hero, 'pointerleave', () => { pointerX = 0; pointerY = 0; requestFrame(); });
    listen(document, 'visibilitychange', () => {
      if (document.hidden) { cancelAnimationFrame(frame); frame = 0; }
      else updateTarget();
    });
    listen(document, 'astro:before-swap', dispose);
    observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible) updateTarget();
      else { cancelAnimationFrame(frame); frame = 0; }
    });
    observer.observe(hero);
    resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(stage);
  } catch (error) {
    console.warn('PSP preview unavailable; showing the static version.', error);
    fallback();
  }
}
