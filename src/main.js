import ImageTracer from 'imagetracerjs';
import UTIF from 'utif';
import './style.css';

const app = document.querySelector('#app');
const accepted = ['png','jpg','jpeg','webp','gif','bmp','avif','tif','tiff'];
let files = [];
let results = new Map();
let selectedId = null;
let mode = 'embed';
let detail = 4;
let colors = 16;
let busy = false;

const icon = (name, size = 18) => {
  const paths = {
    image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
    trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-1 14H6L5 6"/><path d="M10 11v5M14 11v5"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    x: '<path d="m18 6-12 12M6 6l12 12"/>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
    arrow: '<path d="M5 12h14M12 5l7 7-7 7"/>',
    spark: '<path d="m12 3 1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2L12 3Z"/><path d="m19 14 1.2 2.8L23 18l-2.8 1.2L19 22l-1.2-2.8L15 18l2.8-1.2L19 14Z"/>',
  };
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.file}</svg>`;
};

function render() {
  app.innerHTML = `
    <header class="topbar">
      <a class="brand" href="#" aria-label="Image Files to SVG ホーム">
        <span class="brand-mark">${icon('image', 22)}</span>
        <span>Image Files <span class="brand-muted">to</span> SVG</span>
      </a>
      <span class="privacy">${icon('check', 15)} 画像は端末内で処理</span>
    </header>
    <main>
      <section class="hero">
        <div class="eyebrow"><span class="eyebrow-dot"></span> FREE IMAGE CONVERTER</div>
        <h1>画像を、<span>SVG</span>に。</h1>
        <p class="hero-copy">画像ファイルをSVG形式へ変換。見た目を保つ方法も、パスに変換する方法も、これひとつで。</p>
      </section>

      <section class="workspace">
        <div class="panel upload-panel">
          <div class="section-heading">
            <div><span class="step">01</span><h2>画像を追加</h2></div>
            <span class="subtle">${files.length ? `${files.length} ファイル` : '複数ファイル対応'}</span>
          </div>
          <label class="dropzone ${files.length ? 'has-files' : ''}" id="dropzone">
            <input id="fileInput" type="file" accept=".png,.jpg,.jpeg,.webp,.gif,.bmp,.avif,.tif,.tiff,image/*" multiple />
            <span class="upload-icon">${icon('upload', 25)}</span>
            <strong>画像をここにドラッグ＆ドロップ</strong>
            <span class="drop-sub">またはクリックしてファイルを選択</span>
            <span class="format-tags">${['PNG','JPG','WebP','GIF','BMP','AVIF','TIFF'].map(x=>`<i>${x}</i>`).join('')}</span>
          </label>
          ${files.length ? `
            <div class="file-list">
              ${files.map(f => `<div class="file-row ${f.id===selectedId?'active':''}" data-id="${f.id}">
                <div class="file-thumb">${f.preview ? `<img src="${f.preview}" alt="">` : icon('file',20)}</div>
                <div class="file-meta"><strong title="${escapeHtml(f.file.name)}">${escapeHtml(f.file.name)}</strong><span>${formatBytes(f.file.size)} · ${f.status === 'done' ? '変換済み' : f.status === 'error' ? 'エラー' : '待機中'}</span></div>
                <button class="icon-button remove" data-remove="${f.id}" aria-label="削除">${icon('x',16)}</button>
              </div>`).join('')}
            </div>
            <div class="file-actions"><button class="text-button" id="clearAll">${icon('trash',15)} すべて削除</button><span class="subtle">最大ファイル数はブラウザ性能に依存</span></div>
          ` : ''}
        </div>

        <div class="panel settings-panel">
          <div class="section-heading">
            <div><span class="step">02</span><h2>変換設定</h2></div>
          </div>
          <div class="mode-label">変換方式</div>
          <div class="mode-options">
            <button class="mode-card ${mode==='embed'?'chosen':''}" data-mode="embed">
              <span class="mode-icon">${icon('image',20)}</span>
              <span class="mode-title">画像を格納</span>
              <span class="mode-desc">見た目をそのまま維持</span>
              <span class="mode-radio"></span>
            </button>
            <button class="mode-card ${mode==='vector'?'chosen':''}" data-mode="vector">
              <span class="mode-icon">${icon('spark',20)}</span>
              <span class="mode-title">ベクター化</span>
              <span class="mode-desc">輪郭をSVGパスに変換</span>
              <span class="mode-radio"></span>
            </button>
          </div>
          <div class="info-note">
            ${mode==='embed'
              ? '<span class="note-symbol">i</span><p>元画像をSVG内に埋め込みます。写真の見た目を保てますが、画像そのものはベクターにはなりません。</p>'
              : '<span class="note-symbol">i</span><p>色を減らして輪郭をパスに近似します。ロゴやイラスト向けで、写真は元画像と見た目が変わる場合があります。</p>'}
          </div>
          ${mode==='vector' ? `
            <div class="slider-setting">
              <div class="slider-head"><label for="colors">色数</label><strong id="colorsValue">${colors}</strong></div>
              <input type="range" id="colors" min="2" max="32" value="${colors}">
              <div class="range-labels"><span>少ない・軽い</span><span>多い・細かい</span></div>
            </div>
            <div class="slider-setting">
              <div class="slider-head"><label for="detail">ディテール</label><strong id="detailValue">${detail}</strong></div>
              <input type="range" id="detail" min="1" max="10" value="${detail}">
              <div class="range-labels"><span>シンプル</span><span>細かい</span></div>
            </div>
          ` : ''}
          <button id="convertBtn" class="primary-button" ${!files.length || busy ? 'disabled' : ''}>
            ${busy ? '<span class="spinner"></span> 変換中...' : `${icon('spark',18)} ${files.length ? `${files.length}件をSVGに変換` : '画像を追加して変換'}`}
            ${!busy ? `<span class="button-arrow">${icon('arrow',17)}</span>` : ''}
          </button>
          <p class="button-caption">変換後にSVGファイルとして保存できます</p>
        </div>
      </section>

      <section class="results-section ${results.size ? '' : 'empty-results'}">
        <div class="section-heading result-heading">
          <div><span class="step">03</span><h2>変換結果</h2></div>
          ${results.size ? `<button id="downloadAll" class="secondary-button">${icon('download',16)} すべてダウンロード</button>` : ''}
        </div>
        ${results.size ? `
          <div class="results-layout">
            <div class="result-list">
              ${files.filter(f=>results.has(f.id)).map(f=>`<button class="result-item ${selectedId===f.id?'active':''}" data-result="${f.id}">
                <span class="result-mini">${icon('file',19)}</span><span class="result-name">${escapeHtml(f.file.name.replace(/\.[^.]+$/,''))}.svg</span>${icon('check',16)}
              </button>`).join('')}
            </div>
            <div class="preview-panel">
              <div class="preview-toolbar"><span>SVG プレビュー</span><span class="preview-dimensions" id="previewInfo"></span></div>
              <div class="preview-canvas" id="previewCanvas"></div>
              <div class="preview-footer"><div class="result-details" id="resultDetails"></div><button class="primary-button small" id="downloadOne">${icon('download',16)} SVGを保存</button></div>
            </div>
          </div>
        ` : `<div class="results-placeholder"><div class="placeholder-icon">${icon('image',27)}</div><strong>変換結果はここに表示されます</strong><span>画像を追加して、変換方式を選んでください。</span></div>`}
      </section>
      <footer><span>Image Files to SVG</span><span>ローカル処理 · ファイルはアップロードされません</span></footer>
    </main>
    <div class="toast" id="toast" role="status"></div>
  `;
  bindEvents();
  if (results.has(selectedId)) showPreview(selectedId);
}

function bindEvents() {
  const input = document.querySelector('#fileInput');
  input.addEventListener('change', e => addFiles([...e.target.files]));
  const drop = document.querySelector('#dropzone');
  for (const ev of ['dragenter','dragover']) drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('dragging'); });
  for (const ev of ['dragleave','drop']) drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('dragging'); });
  drop.addEventListener('drop', e => addFiles([...e.dataTransfer.files]));
  document.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>{mode=b.dataset.mode;render();}));
  document.querySelectorAll('[data-id]').forEach(el=>el.addEventListener('click', e=>{
    if(e.target.closest('[data-remove]')) return;
    selectedId=el.dataset.id; render();
  }));
  document.querySelectorAll('[data-remove]').forEach(b=>b.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();removeFile(b.dataset.remove);}));
  document.querySelector('#clearAll')?.addEventListener('click', clearAll);
  document.querySelector('#convertBtn')?.addEventListener('click', convertAll);
  document.querySelector('#colors')?.addEventListener('input',e=>{colors=+e.target.value;document.querySelector('#colorsValue').textContent=colors;});
  document.querySelector('#detail')?.addEventListener('input',e=>{detail=+e.target.value;document.querySelector('#detailValue').textContent=detail;});
  document.querySelector('#downloadOne')?.addEventListener('click',()=>downloadResult(selectedId));
  document.querySelector('#downloadAll')?.addEventListener('click',downloadAll);
  document.querySelectorAll('[data-result]').forEach(b=>b.addEventListener('click',()=>{selectedId=b.dataset.result;render();}));
}

function addFiles(incoming) {
  const valid = [];
  const rejected = [];
  for (const file of incoming) {
    const ext = file.name.split('.').pop().toLowerCase();
    if (!accepted.includes(ext)) { rejected.push(file.name); continue; }
    if (files.some(x=>x.file.name===file.name && x.file.size===file.size)) continue;
    const item = {id: crypto.randomUUID(), file, status:'ready', preview:null, width:0, height:0};
    files.push(item); valid.push(item);
    if (file.type.startsWith('image/') && !['image/tiff','image/x-tiff'].includes(file.type)) {
      item.preview = URL.createObjectURL(file);
    }
  }
  if (valid.length && !selectedId) selectedId=valid[0].id;
  if (rejected.length) toast(`未対応の形式をスキップしました: ${rejected.slice(0,2).join(', ')}`);
  render();
}

function removeFile(id) {
  const f=files.find(x=>x.id===id);
  if(f?.preview) URL.revokeObjectURL(f.preview);
  files=files.filter(x=>x.id!==id); results.delete(id);
  if(selectedId===id) selectedId=files[0]?.id||null;
  render();
}
function clearAll() {
  files.forEach(f=>{if(f.preview) URL.revokeObjectURL(f.preview);});
  files=[]; results.clear(); selectedId=null; render();
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function formatBytes(n) {
  if(n<1024)return `${n} B`;
  if(n<1048576)return `${(n/1024).toFixed(1)} KB`;
  return `${(n/1048576).toFixed(2)} MB`;
}
function toast(msg) {
  const el=document.querySelector('#toast'); if(!el)return;
  el.textContent=msg; el.classList.add('show'); setTimeout(()=>el.classList.remove('show'),3500);
}
function loadImage(file) {
  return new Promise((resolve,reject)=>{
    const url=URL.createObjectURL(file), img=new Image();
    img.onload=()=>{URL.revokeObjectURL(url);resolve(img);};
    img.onerror=()=>{URL.revokeObjectURL(url);reject(new Error('この画像形式をブラウザで読み込めません。'));};
    img.src=url;
  });
}
async function imageToCanvas(file) {
  const ext=file.name.split('.').pop().toLowerCase();
  let source, originalWidth, originalHeight;
  if(['tif','tiff'].includes(ext)) {
    const buffer=await file.arrayBuffer();
    const ifds=UTIF.decode(buffer);
    if(!ifds || !ifds.length) throw new Error('TIFF画像を読み込めませんでした。');
    UTIF.decodeImage(buffer,ifds[0]);
    originalWidth=ifds[0].width;
    originalHeight=ifds[0].height;
    const rgba=UTIF.toRGBA8(ifds[0]);
    source={data:rgba,width:originalWidth,height:originalHeight};
  } else {
    const img=await loadImage(file);
    originalWidth=img.naturalWidth;
    originalHeight=img.naturalHeight;
    source=img;
  }
  const max=1800, scale=Math.min(1,max/Math.max(originalWidth,originalHeight));
  const canvas=document.createElement('canvas');
  canvas.width=Math.max(1,Math.round(originalWidth*scale));
  canvas.height=Math.max(1,Math.round(originalHeight*scale));
  const ctx=canvas.getContext('2d',{willReadFrequently:true});
  if(source.data) {
    const temp=document.createElement('canvas');
    temp.width=source.width; temp.height=source.height;
    temp.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(source.data),source.width,source.height),0,0);
    ctx.drawImage(temp,0,0,canvas.width,canvas.height);
  } else {
    ctx.drawImage(source,0,0,canvas.width,canvas.height);
  }
  return {canvas,width:originalWidth,height:originalHeight};
}
function escapeXml(s) {
  return String(s).replace(/[<>&'"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;',"'":'&apos;','"':'&quot;'}[c]));
}
function embeddedSvg(dataUrl,width,height) {
  return `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><image width="${width}" height="${height}" href="${dataUrl}" xlink:href="${dataUrl}" preserveAspectRatio="none"/></svg>`;
}
async function convertOne(item) {
  const {canvas,width,height}=await imageToCanvas(item.file);
  let svg;
  if(mode==='embed') {
    const dataUrl=canvas.toDataURL('image/png');
    svg=embeddedSvg(dataUrl,canvas.width,canvas.height);
  } else {
    const ctx=canvas.getContext('2d',{willReadFrequently:true});
    const imageData=ctx.getImageData(0,0,canvas.width,canvas.height);
    const options={
      numberofcolors:colors,
      ltres:Math.max(.1,1.2-detail*.1),
      qtres:Math.max(.1,1.2-detail*.1),
      pathomit: detail>=8 ? 2 : detail>=5 ? 4 : 8,
      rightangleenhance: detail>=6,
      colorsampling: 2,
      scale: 1,
      strokewidth: 0,
      viewbox: true,
      desc: false,
      linefilter: true,
      layering: 0,
      blurradius: 0,
      blurdelta: 20
    };
    svg=ImageTracer.imagedataToSVG(imageData,options);
    svg=svg.replace(/<svg\b/,`<svg width="${width}" height="${height}"`);
  }
  return {svg,width,height,sourceSize:item.file.size};
}
async function convertAll() {
  if(busy||!files.length)return;
  busy=true; render();
  const queue=[...files];
  let completed=0, failed=0;
  for(const item of queue) {
    try {
      const result=await convertOne(item);
      results.set(item.id,{...result,name:item.file.name.replace(/\.[^.]+$/,'')+'.svg',mode});
      item.status='done'; item.width=result.width; item.height=result.height;
      selectedId=item.id; completed++;
    } catch(err) {
      item.status='error'; failed++; toast(`${item.file.name}: ${err.message}`);
    }
    // Update progress without rebuilding the whole interface every item.
    const btn=document.querySelector('#convertBtn');
    if(btn) btn.innerHTML=`<span class="spinner"></span> 変換中 ${completed+failed}/${queue.length}...`;
  }
  busy=false; render();
  toast(failed ? `${completed}件を変換、${failed}件は変換できませんでした。` : `${completed}件のSVG変換が完了しました。`);
}
function showPreview(id) {
  const r=results.get(id); if(!r)return;
  const canvas=document.querySelector('#previewCanvas');
  canvas.innerHTML=r.svg;
  const svg=canvas.querySelector('svg');
  if(svg){svg.removeAttribute('width');svg.removeAttribute('height');svg.style.maxWidth='100%';svg.style.maxHeight='100%';svg.style.width='auto';svg.style.height='auto';}
  document.querySelector('#previewInfo').textContent=`${r.width} × ${r.height}`;
  document.querySelector('#resultDetails').innerHTML=`<strong>${escapeHtml(r.name)}</strong><span>${formatBytes(new Blob([r.svg]).size)} · ${r.mode==='embed'?'画像格納':'ベクター化'}</span>`;
}
function downloadResult(id) {
  const r=results.get(id); if(!r)return;
  const blob=new Blob([r.svg],{type:'image/svg+xml;charset=utf-8'});
  const url=URL.createObjectURL(blob), a=document.createElement('a');
  a.href=url;a.download=r.name;a.click();URL.revokeObjectURL(url);
}
function downloadAll() {
  const ready=files.filter(f=>results.has(f.id));
  ready.forEach((f,i)=>setTimeout(()=>downloadResult(f.id),i*250));
}
render();
