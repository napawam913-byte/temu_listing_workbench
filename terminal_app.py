from __future__ import annotations

import base64
import atexit
import hashlib
import hmac
import json
import marshal
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
import weakref
from pathlib import Path
from typing import Any


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
BASE_CODE_PATHS = [
    APP_DIR / "work" / "terminal_app_base.pyc",
    Path(getattr(sys, "_MEIPASS", APP_DIR)) / "terminal_app_base.pyc",
    APP_DIR / "terminal_app_base.pyc",
    APP_DIR / "__pycache__" / "terminal_app.cpython-313.pyc",
]

DEFAULT_IMAGE_POSTPROCESS = {
    "enabled": True,
    "targetWidth": 800,
    "targetHeight": 800,
    "quality": 88,
    "maxBytes": 2 * 1024 * 1024,
    "minSourceWidth": 300,
    "minSourceHeight": 300,
    "outputFormat": "jpg",
    "mode": "pad",
    "background": "#FFFFFF",
    "compressorPath": "C:/Users/AA/Desktop/优化工具/图片压缩起.exe",
}

DEFAULT_FEISHU_BOT = {
    "enabled": False,
    "webhookUrl": "",
    "secret": "",
    "notifyOnError": True,
    "notifyOnStop": True,
    "notifyOnSuccess": False,
    "keyword": "店小秘",
}

DEFAULT_AI_CONFIG = {
    "providerName": "LaoZhang API",
    "baseUrl": "https://api.laozhang.ai/v1",
    "apiKey": "",
    "model": "gpt-4o-mini",
    "timeoutMs": 45000,
}

LIST_VISIBLE_WAREHOUSE_OPTIONS_JS = r"""
() => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function visible(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'&&r.bottom>=0&&r.right>=0&&r.top<=innerHeight&&r.left<=innerWidth;
  }
  const rows=[...document.querySelectorAll('.ant-select-dropdown .ant-select-item-option,.ant-select-dropdown [role="option"],.ant-select-item-option-content')].filter(visible);
  const out=[];
  const used=new Set();
  for(const row of rows){
    const text=clean(row.getAttribute('title')||row.getAttribute('label')||row.getAttribute('aria-label')||row.innerText||row.textContent||'');
    if(!text) continue;
    if(text==='全部') continue;
    const key=text.toLowerCase();
    if(used.has(key)) continue;
    used.add(key);
    out.push(text);
  }
  return out;
}
"""

SYNC_WAREHOUSE_SELECTION_TO_TEMPLATE_JS = r"""
({ targets }) => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function norm(s){return clean(s).replace(/[\s\-_【】\[\]（）()，,、/]+/g,'').toLowerCase()}
  function baseName(s){return clean(s).replace(/(（其他）|\(其他\)|（其它）|\(其它\))$/,'').trim()}
  function baseNorm(s){return norm(baseName(s))}
  function ignoreText(s){const t=clean(s); return !t || /^\+\s*\d+$/.test(t) || /^(全部|请选择|请选择配件|输入搜索值)$/i.test(t)}
  function visible(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'&&r.bottom>=0&&r.right>=0&&r.top<=innerHeight&&r.left<=innerWidth;
  }
  function warehouseRoot(){
    const explicit=document.querySelector('.skuWarehouse');
    if(explicit){
      const rows=[...explicit.querySelectorAll('.flex-y-center,.ant-row,.ant-form-item,[class*="warehouse"],[class*="sku"]')];
      const row=rows
        .map(el => ({el, text:clean(el.innerText||el.textContent||''), rect:el.getBoundingClientRect()}))
        .filter(item => item.text.includes('选择仓库') && item.el.querySelector('.ant-select,.ant-select-selector,[class*="ant-select"]'))
        .sort((a,b)=>a.rect.height-b.rect.height || a.text.length-b.text.length)[0]?.el;
      return row || explicit;
    }
    const nodes=[...document.querySelectorAll('body *')].filter(visible);
    const label=nodes
      .map(el => ({el, text:clean(el.innerText||el.textContent||'')}))
      .filter(item => item.text && item.text.length<=80 && /选择仓库/.test(item.text))
      .sort((a,b)=>a.text.length-b.text.length)[0]?.el;
    return label?.closest('.ant-form-item,.ant-row,[class*="form-item"],[class*="sku"],[class*="warehouse"]') || label?.parentElement || null;
  }
  function warehouseBox(){
    const root=warehouseRoot();
    const select=root?.querySelector('.ant-select,.ant-select-selector,[class*="ant-select"]');
    if(!select) return null;
    const r=select.getBoundingClientRect();
    return {x:r.x,y:r.y,w:r.width,h:r.height};
  }
  function nearWarehouse(el){
    const box=warehouseBox();
    if(!box) return true;
    const r=el.getBoundingClientRect();
    const cx=r.x+r.width/2;
    return cx>=box.x-100 && cx<=box.x+box.w+240 && r.top>=box.y-100 && r.top<=box.y+760;
  }
  function keep(text){
    if(ignoreText(text)) return true;
    const n=norm(text);
    const b=baseNorm(text);
    for(const target of targetKeys){
      if(n===target.norm || b===target.base) return true;
    }
    return false;
  }
  function clickElement(el){
    if(!el) return false;
    el.scrollIntoView({block:'center', inline:'nearest'});
    const r=el.getBoundingClientRect();
    const init={bubbles:true,cancelable:true,view:window,clientX:r.x+r.width/2,clientY:r.y+r.height/2};
    for(const type of ['mousemove','mousedown','mouseup','click']){
      el.dispatchEvent(new MouseEvent(type,init));
    }
    return true;
  }
  function optionText(opt){
    const content=opt.querySelector('.ant-select-item-option-content,[class*="option-content"]');
    return clean(opt.getAttribute('label')||opt.getAttribute('title')||opt.getAttribute('aria-label')||content?.innerText||content?.textContent||opt.innerText||opt.textContent||'');
  }
  function optionSelected(opt){
    const cls=String(opt.className||'');
    if(opt.getAttribute('aria-selected')==='true' || opt.getAttribute('aria-checked')==='true') return true;
    if(/ant-select-item-option-selected/i.test(cls)) return true;
    const checkbox=opt.querySelector('input[type="checkbox"],input[type="radio"]');
    if(checkbox && checkbox.checked) return true;
    if(opt.querySelector('.ant-checkbox-checked,.ant-checkbox-wrapper-checked,.ant-radio-checked,.in-check-box-checked,.in-checked,.is-checked,[aria-checked="true"]')) return true;
    return false;
  }
  const targetKeys=(targets||[]).map(text => ({norm:norm(text), base:baseNorm(text)})).filter(item => item.norm || item.base);
  const root=warehouseRoot();
  if(!root) return {ok:false,error:'找不到仓库模块',removed:[],kept:[],failed:[],ignored:[]};
  const removed=[];
  const kept=[];
  const failed=[];
  const ignored=[];
  const tagNodes=[...root.querySelectorAll('.ant-select-selection-item')].filter(visible);
  for(const tag of tagNodes){
    const content=tag.querySelector('.ant-select-selection-item-content');
    const text=clean(tag.getAttribute('title') || content?.getAttribute('title') || content?.textContent || tag.textContent || '');
    if(ignoreText(text)){ ignored.push(text); continue; }
    if(keep(text)){
      kept.push(text);
      continue;
    }
    const remove=tag.querySelector('.ant-select-selection-item-remove,.anticon-close,[aria-label*="close" i],[aria-label*="remove" i]');
    if(remove && clickElement(remove)){
      removed.push(text);
    }else{
      failed.push(text);
    }
  }
  const options=[...document.querySelectorAll('.ant-select-dropdown .ant-select-item-option,.ant-select-dropdown [role="option"]')].filter(el => visible(el) && nearWarehouse(el));
  for(const opt of options){
    const selected=optionSelected(opt);
    if(!selected) continue;
    const text=optionText(opt);
    if(ignoreText(text)){ ignored.push(text); continue; }
    if(keep(text)){ kept.push(text); continue; }
    const checkbox=opt.querySelector('input[type="checkbox"],input[type="radio"]');
    const clickTarget=checkbox || opt.querySelector('.ant-checkbox,.ant-checkbox-wrapper,.ant-select-item-option-content') || opt;
    if(clickElement(clickTarget)){
      removed.push(text);
    }else{
      failed.push(text);
    }
  }
  return {ok:true, removed:[...new Set(removed)], kept:[...new Set(kept)], failed:[...new Set(failed)], ignored:[...new Set(ignored)]};
}
"""

WAREHOUSE_SELECTED_STATE_WITH_CHECKBOX_JS = r"""
(targets) => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function norm(s){return clean(s).replace(/[\s\-_【】\[\]（）()，,、/]+/g,'').toLowerCase()}
  function baseName(s){return clean(s).replace(/(（其他）|\(其他\)|（其它）|\(其它\))$/,'').trim()}
  function baseNorm(s){return norm(baseName(s))}
  function ignoreText(s){const t=clean(s); return !t || /^\+\s*\d+$/.test(t) || /^(全部|请选择|请选择配件|输入搜索值)$/i.test(t)}
  function visible(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'&&r.bottom>=0&&r.right>=0&&r.top<=innerHeight&&r.left<=innerWidth;
  }
  function warehouseRoot(){
    const explicit=document.querySelector('.skuWarehouse');
    if(explicit){
      const rows=[...explicit.querySelectorAll('.flex-y-center,.ant-row,.ant-form-item,[class*="warehouse"],[class*="sku"]')];
      const row=rows
        .map(el => ({el, text:clean(el.innerText||el.textContent||''), rect:el.getBoundingClientRect()}))
        .filter(item => item.text.includes('选择仓库') && item.el.querySelector('.ant-select,.ant-select-selector,[class*="ant-select"]'))
        .sort((a,b)=>a.rect.height-b.rect.height || a.text.length-b.text.length)[0]?.el;
      return row || explicit;
    }
    const nodes=[...document.querySelectorAll('.ant-form-item,.ant-row,[class*="sku"],[class*="warehouse"]')];
    for(const node of nodes){
      const text=clean(node.innerText||node.textContent||'');
      if(text.includes('选择仓库')){
        const select=node.querySelector('.ant-select,.ant-select-selector,[class*="ant-select"]');
        if(select) return node;
      }
    }
    return null;
  }
  function warehouseBox(){
    const root=warehouseRoot();
    const select=root?.querySelector('.ant-select,.ant-select-selector,[class*="ant-select"]');
    if(!select) return null;
    const r=select.getBoundingClientRect();
    return {x:r.x,y:r.y,w:r.width,h:r.height};
  }
  function nearWarehouse(el){
    const box=warehouseBox();
    if(!box) return true;
    const r=el.getBoundingClientRect();
    const cx=r.x+r.width/2;
    return cx>=box.x-100 && cx<=box.x+box.w+220 && r.top>=box.y-80 && r.top<=box.y+760;
  }
  function optionText(opt){
    const content=opt.querySelector('.ant-select-item-option-content,[class*="option-content"]');
    return clean(opt.getAttribute('label')||opt.getAttribute('title')||opt.getAttribute('aria-label')||content?.innerText||content?.textContent||opt.innerText||opt.textContent||'');
  }
  function optionSelected(opt){
    const cls=String(opt.className||'');
    if(opt.getAttribute('aria-selected')==='true' || opt.getAttribute('aria-checked')==='true') return true;
    if(/ant-select-item-option-selected/i.test(cls)) return true;
    const checkbox=opt.querySelector('input[type="checkbox"],input[type="radio"]');
    if(checkbox && checkbox.checked) return true;
    const checkedNode=opt.querySelector('.ant-checkbox-checked,.ant-checkbox-wrapper-checked,.ant-radio-checked,.in-check-box-checked,.in-checked,.is-checked,[aria-checked="true"]');
    if(checkedNode) return true;
    return /\bchecked\b|\bselected\b|ant-checkbox-checked|ant-radio-checked|in-checked|is-checked/i.test(cls);
  }
  const root=warehouseRoot();
  const mainText=clean(root?.querySelector('.ant-select')?.textContent || root?.textContent || '');
  const overflowText=clean(root?.querySelector('.ant-select-selection-overflow-item-rest')?.textContent || '');
  const overflowMatch=(mainText + ' ' + overflowText).match(/\+\s*(\d+)/);
  const overflowCount=overflowMatch ? parseInt(overflowMatch[1], 10) : 0;
  const selected=[];
  const tagNodes=[...root?.querySelectorAll('.ant-select-selection-item')||[]];
  for(const tag of tagNodes){
    const content=tag.querySelector('.ant-select-selection-item-content');
    const txt=clean(tag.getAttribute('title')||content?.getAttribute('title')||content?.textContent||tag.textContent||'');
    if(txt && !ignoreText(txt)) selected.push(txt);
  }
  const options=[...document.querySelectorAll('.ant-select-dropdown .ant-select-item-option,.ant-select-dropdown [role="option"]')].filter(el => visible(el) && nearWarehouse(el));
  const seen=[];
  for(const opt of options){
    const txt=optionText(opt);
    if(txt && !ignoreText(txt)) seen.push(txt);
    if(ignoreText(txt) || !optionSelected(opt)) continue;
    selected.push(txt);
  }
  const selectedTexts=[mainText,...selected].filter(Boolean);
  const allText=selectedTexts.join('|');
  const allNorm=norm(allText);
  const selectedNorms=selectedTexts.map(norm).filter(Boolean);
  const selectedBaseNorms=selectedTexts.map(baseNorm).filter(Boolean);
  const states={};
  const targetList=(targets||[]).map(clean).filter(Boolean);
  const selectedTargetCount=selected.filter(item => {
    const itemNorm=norm(item);
    const itemBase=baseNorm(item);
    return targetList.some(target => itemNorm===norm(target) || itemBase===baseNorm(target));
  }).length;
  const collapsedMatchesTargets=overflowCount>0 && selectedTargetCount>0 && selectedTargetCount + overflowCount >= targetList.length;
  for(const target of targets||[]){
    const targetNorm=norm(target);
    const targetBase=baseNorm(target);
    states[target]=!!targetNorm && (collapsedMatchesTargets ||
      allNorm.includes(targetNorm) ||
      selectedNorms.some(item => item===targetNorm || item.includes(targetNorm) || targetNorm.includes(item)) ||
      selectedBaseNorms.some(item => item===targetBase || item.includes(targetBase) || targetBase.includes(item))
    );
  }
  return {states, selected:[...new Set(selected)], seen:[...new Set(seen)], mainText, overflowCount, collapsedMatchesTargets};
}
"""

WAREHOUSE_EXACT_SELECTION_STATE_JS = r"""
({ targets }) => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function norm(s){return clean(s).replace(/[\s\-_【】\[\]（）()，,、/]+/g,'').toLowerCase()}
  function baseName(s){return clean(s).replace(/(（其他）|\(其他\)|（其它）|\(其它\))$/,'').trim()}
  function baseNorm(s){return norm(baseName(s))}
  function ignoreText(s){const t=clean(s); return !t || /^\+\s*\d+$/.test(t) || /^(全部|请选择|请选择配件|输入搜索值)$/i.test(t)}
  function visible(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'&&r.bottom>=0&&r.right>=0&&r.top<=innerHeight&&r.left<=innerWidth;
  }
  function point(el){
    if(!el) return null;
    const r=el.getBoundingClientRect();
    return {x:r.x+r.width/2, y:r.y+r.height/2};
  }
  function warehouseRoot(){
    const explicit=document.querySelector('.skuWarehouse');
    if(explicit){
      const rows=[...explicit.querySelectorAll('.flex-y-center,.ant-row,.ant-form-item,[class*="warehouse"],[class*="sku"]')];
      const row=rows
        .map(el => ({el, text:clean(el.innerText||el.textContent||''), rect:el.getBoundingClientRect()}))
        .filter(item => item.text.includes('选择仓库') && item.el.querySelector('.ant-select,.ant-select-selector,[class*="ant-select"]'))
        .sort((a,b)=>a.rect.height-b.rect.height || a.text.length-b.text.length)[0]?.el;
      return row || explicit;
    }
    const nodes=[...document.querySelectorAll('.ant-form-item,.ant-row,[class*="sku"],[class*="warehouse"]')];
    for(const node of nodes){
      const text=clean(node.innerText||node.textContent||'');
      if(text.includes('选择仓库')){
        const select=node.querySelector('.ant-select,.ant-select-selector,[class*="ant-select"]');
        if(select) return node;
      }
    }
    return null;
  }
  function warehouseBox(){
    const root=warehouseRoot();
    const select=root?.querySelector('.ant-select,.ant-select-selector,[class*="ant-select"]');
    if(!select) return null;
    const r=select.getBoundingClientRect();
    return {x:r.x,y:r.y,w:r.width,h:r.height};
  }
  function nearWarehouse(el){
    const box=warehouseBox();
    if(!box) return true;
    const r=el.getBoundingClientRect();
    const cx=r.x+r.width/2;
    return cx>=box.x-120 && cx<=box.x+box.w+260 && r.top>=box.y-120 && r.top<=box.y+800;
  }
  function optionText(opt){
    const content=opt.querySelector('.ant-select-item-option-content,[class*="option-content"]');
    return clean(opt.getAttribute('label')||opt.getAttribute('title')||opt.getAttribute('aria-label')||content?.innerText||content?.textContent||opt.innerText||opt.textContent||'');
  }
  function optionSelected(opt){
    const cls=String(opt.className||'');
    if(opt.getAttribute('aria-selected')==='true' || opt.getAttribute('aria-checked')==='true') return true;
    if(/ant-select-item-option-selected/i.test(cls)) return true;
    const checkbox=opt.querySelector('input[type="checkbox"],input[type="radio"]');
    if(checkbox && checkbox.checked) return true;
    if(opt.querySelector('.ant-checkbox-checked,.ant-checkbox-wrapper-checked,.ant-radio-checked,.in-check-box-checked,.in-checked,.is-checked,[aria-checked="true"]')) return true;
    return /\bchecked\b|\bselected\b|ant-checkbox-checked|ant-radio-checked|in-checked|is-checked/i.test(cls);
  }
  function matchesTarget(text){
    const n=norm(text);
    const b=baseNorm(text);
    return targetKeys.some(target => n===target.norm || b===target.base);
  }
  function sameWarehouse(a,b){
    return norm(a)===norm(b) || baseNorm(a)===baseNorm(b);
  }
  const targetList=(targets||[]).map(clean).filter(Boolean);
  const targetKeys=targetList.map(text => ({text, norm:norm(text), base:baseNorm(text)})).filter(item => item.norm || item.base);
  const root=warehouseRoot();
  if(!root) return {ok:false,error:'找不到仓库模块',states:{},selected:[],missingTargets:targetList,extraSelected:[],extraPoints:[],seen:[],mainText:''};
  const mainText=clean(root.querySelector('.ant-select')?.textContent || root.textContent || '');
  const overflowText=clean(root.querySelector('.ant-select-selection-overflow-item-rest')?.textContent || '');
  const overflowMatch=(mainText + ' ' + overflowText).match(/\+\s*(\d+)/);
  const overflowCount=overflowMatch ? parseInt(overflowMatch[1], 10) : 0;
  const selectedItems=[];
  const seen=[];
  const tagNodes=[...root.querySelectorAll('.ant-select-selection-item')];
  for(const tag of tagNodes){
    const content=tag.querySelector('.ant-select-selection-item-content');
    const text=clean(tag.getAttribute('title') || content?.getAttribute('title') || content?.textContent || tag.textContent || '');
    if(ignoreText(text)) continue;
    const remove=tag.querySelector('.ant-select-selection-item-remove,.anticon-close,[aria-label*="close" i],[aria-label*="remove" i]');
    selectedItems.push({text, source:'tag', point:point(remove || tag)});
  }
  const options=[...document.querySelectorAll('.ant-select-dropdown .ant-select-item-option,.ant-select-dropdown [role="option"]')].filter(el => visible(el) && nearWarehouse(el));
  for(const opt of options){
    const text=optionText(opt);
    if(text && !ignoreText(text)) seen.push(text);
    if(ignoreText(text) || !optionSelected(opt)) continue;
    const clickTarget=opt.querySelector('.ant-checkbox-wrapper,.ant-checkbox,input[type="checkbox"],input[type="radio"],.ant-select-item-option-content') || opt;
    selectedItems.push({text, source:'option', point:point(clickTarget)});
  }
  const selected=[];
  const selectedKeys=new Set();
  const extraSelected=[];
  const extraPoints=[];
  for(const item of selectedItems){
    const key=baseNorm(item.text) || norm(item.text);
    if(!key || selectedKeys.has(key)) continue;
    selectedKeys.add(key);
    selected.push(item.text);
    if(!matchesTarget(item.text)){
      extraSelected.push(item.text);
      if(item.point) extraPoints.push({text:item.text, source:item.source, x:item.point.x, y:item.point.y});
    }
  }
  const states={};
  const missingTargets=[];
  for(const target of targetList){
    const matched=selected.some(item => sameWarehouse(item, target));
    states[target]=matched;
    if(!matched) missingTargets.push(target);
  }
  let inferredFromCollapsedTags=false;
  if(missingTargets.length && overflowCount>0 && extraSelected.length===0){
    const selectedTargetCount=selected.filter(item => matchesTarget(item)).length;
    if(selectedTargetCount>0 && selectedTargetCount + overflowCount >= targetList.length){
      for(const target of targetList){
        if(!selected.some(item => sameWarehouse(item, target))){
          selected.push(target);
        }
        states[target]=true;
      }
      missingTargets.length=0;
      inferredFromCollapsedTags=true;
    }
  }
  return {
    ok: missingTargets.length===0 && extraSelected.length===0,
    states,
    selected,
    missingTargets,
    extraSelected,
    extraPoints,
    seen:[...new Set(seen)],
    mainText,
    overflowCount,
    inferredFromCollapsedTags
  };
}
"""


def _load_base_namespace() -> dict[str, Any]:
    searched: list[str] = []
    for path in BASE_CODE_PATHS:
        searched.append(str(path))
        if not path.exists():
            continue
        ns: dict[str, Any] = {
            "__name__": "_dxm_temu_terminal_base",
            "__file__": str(Path(__file__).resolve()),
        }
        data = path.read_bytes()
        exec(marshal.loads(data[16:]), ns)
        return ns
    raise RuntimeError("没有找到机器人基座程序；已查找：" + " | ".join(searched))


BASE = _load_base_namespace()

PATCHED_BASIC_ATTR_SCAN_JS = r"""
() => {
  const moduleRoot = findModuleRoot('基本信息');
  if (!moduleRoot) return { ok: false, error: '找不到基本信息模块', attrs: [] };
  const attrRoot = findProductAttrRoot(moduleRoot);
  if (!attrRoot) return { ok: false, error: '找不到基本信息里的产品属性区域', attrs: [] };
  const attrs = collectAttrs(attrRoot);
  const productInfo = collectProductInfo(moduleRoot, attrs);
  return { ok: true, module: '基本信息', area: '产品属性', productInfo, attrs };
  function clean(s) { return (s || '').replace(/[\n\r\t]+/g, ' ').replace(/\s+/g, ' ').trim(); }
  function rendered(el) {
    if (!el) return false;
    const st = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return st.display !== 'none' && st.visibility !== 'hidden' && r.width >= 0 && r.height >= 0;
  }
  function findModuleRoot(name) {
    const heads = [...document.querySelectorAll('h4, .form-card-title, .form-card-header, [class*="form-card-title"], [class*="form-card-header"]')];
    const exact = heads.find(h => clean(h.textContent).startsWith(name));
    return exact ? (exact.closest('.form-card') || exact.closest('[class*="form-card"]') || exact.parentElement) : null;
  }
  function findProductAttrRoot(root) {
    const nodes = [...root.querySelectorAll('label, .ant-form-item-label, [class*="form-item-label"], span, div')];
    const label = nodes.find(el => clean(el.textContent).replace(/[:：*＊]/g, '') === '产品属性');
    if (!label) return null;
    const item = label.closest('.ant-form-item') || label.closest('[class*="form-item"]') || label.parentElement;
    return (item && (item.querySelector('.ant-form-item-control') || item.querySelector('[class*="form-item-control"]'))) || item;
  }
  function meaningfulInputs(item) {
    return [...item.querySelectorAll('textarea, input')]
      .filter(rendered)
      .filter(input => (input.getAttribute('type') || '').toLowerCase() !== 'hidden')
      .filter(input => !String(input.className || '').includes('ant-select-selection-search-input'))
      .filter(input => !input.closest('.ant-select'));
  }
  function collectAttrs(root) {
    const labelNodes = [...root.querySelectorAll('[class*="attr-label"], .ant-form-item-label, [class*="form-item-label"]')].filter(el => !el.closest('.ant-checkbox-wrapper') && !el.querySelector('input[type="checkbox"]'));
    const seen = new Set(), attrs = [];
    for (const node of labelNodes) {
      let label = clean(node.textContent).replace(/^[*＊]+/, '').replace(/[:：]$/, '').replace(/请选择产品属性/g, '').trim();
      if (!label || label === '产品属性' || label.length > 40 || seen.has(label)) continue;
      const item = node.closest('.ant-form-item') || node.closest('[class*="form-item"]') || node.closest('.ant-row') || node.parentElement;
      if (!item) continue;
      const component = detectComponent(item, label);
      if (component === 'unknown') continue;
      const value = getValue(item, component);
      const placeholder = getPlaceholder(item);
      const r = item.getBoundingClientRect();
      attrs.push({
        index: attrs.length,
        attrId: item.getAttribute('data-attr-id') || item.getAttribute('attr-id') || '',
        label,
        required: /^[*＊]/.test(clean(node.textContent)) || String(node.className).includes('required') || !!node.querySelector('[class*="required"]') || String(item.className).includes('required'),
        component,
        value,
        placeholder,
        visible: r.width > 0 && r.height > 0
      });
      seen.add(label);
    }
    return attrs;
  }
  function detectComponent(item, label) {
    if (item.querySelector('.ant-checkbox-wrapper, .ant-checkbox, input[type="checkbox"]')) return 'checkbox-group';
    if (item.querySelector('.ant-select, [class*="ant-select"]') && (/%/.test(clean(item.textContent)) || clean(label).includes('成分'))) return 'ant-select';
    if (meaningfulInputs(item).length) return 'input';
    if (item.querySelector('.ant-select, [class*="ant-select"]')) return 'ant-select';
    return 'unknown';
  }
  function getValue(item, component) {
    if (component === 'checkbox-group') return [...item.querySelectorAll('.ant-checkbox-wrapper-checked, label:has(input[type="checkbox"]:checked)')].map(x => clean(x.textContent)).filter(Boolean).join('、');
    if (component === 'input') return meaningfulInputs(item).map(input => clean(input.value || '')).filter(Boolean).join('、');
    if (component === 'ant-select') {
      const placeholder = getPlaceholder(item);
      return [...item.querySelectorAll('.ant-select-selection-item, .ant-select-selection-overflow-item, [class*="selection-item"]')].map(x => clean(x.textContent)).filter(x => x && x !== placeholder && x !== '×').join('、');
    }
    return '';
  }
  function getPlaceholder(item) {
    const p = item.querySelector('.ant-select-selection-placeholder, [class*="placeholder"]');
    if (p) return clean(p.textContent);
    const input = meaningfulInputs(item)[0] || item.querySelector('textarea, input');
    return input ? clean(input.getAttribute('placeholder') || '') : '';
  }
  function readByLabel(scope, label) {
    const nodes = [...scope.querySelectorAll('label, .ant-form-item-label, [class*="form-item-label"]')];
    const found = nodes.find(el => clean(el.textContent).includes(label));
    if (!found) return '';
    const item = found.closest('.ant-form-item') || found.closest('[class*="form-item"]') || found.parentElement;
    const input = item && item.querySelector('input, textarea');
    if (input && input.value) return clean(input.value);
    return item ? [...item.querySelectorAll('.ant-select-selection-item, [class*="selection-item"]')].map(x => clean(x.textContent)).filter(Boolean).join('、') : '';
  }
  function collectProductInfo(moduleRoot, attrs) {
    const categoryPath = readCategoryPath(moduleRoot);
    const productModule = findModuleRoot('产品信息');
    const productTitle = productModule ? readByLabel(productModule, '产品标题') : '';
    return { url: location.href, category: categoryPath, title: productTitle || readByLabel(moduleRoot, '产品分类'), englishTitle: productModule ? readByLabel(productModule, '英文标题') : '', sourceUrl: productModule ? readByLabel(productModule, '来源URL') : '', filledAttrs: attrs.filter(a => a.value).map(a => `${a.label}: ${a.value}`) };
  }
  function readCategoryPath(moduleRoot) {
    const directCategoryNodes = [...moduleRoot.querySelectorAll('.category-list, [class*="category-list"]')]
      .map(el => clean(el.innerText || el.textContent))
      .filter(t => t && t.includes('>'));
    for (const text of directCategoryNodes) {
      const category = normalizeCategoryPath(text);
      if (category) return category;
    }
    const attrRoot = findProductAttrRoot(moduleRoot);
    const bad = /产品属性|平方克重|材料组成|成分|风格|图案|材料|形状|品牌名|护理说明|请选择产品属性/;
    const nodes = [...moduleRoot.querySelectorAll('*')]
      .filter(el => !(attrRoot && attrRoot.contains(el)))
      .map(el => clean(el.innerText || el.textContent))
      .filter(t => t && t.includes('>') && t.length <= 180 && !bad.test(t))
      .sort((a, b) => a.length - b.length);
    if (nodes.length) return normalizeCategoryPath(nodes[0]);
    const text = clean(moduleRoot.innerText || moduleRoot.textContent);
    return normalizeCategoryPath(text);
  }
  function normalizeCategoryPath(text) {
    let value = clean(text).replace(/＞/g, '>');
    if (value.includes('选择分类')) value = value.split('选择分类').pop();
    else if (value.includes('产品分类')) value = value.split('产品分类').pop();
    value = value.split('产品属性')[0];
    const parts = value.split('>').map(p => clean(p).replace(/^(产品分类|选择分类)/, '').trim()).filter(Boolean);
    return parts.length >= 2 ? parts.slice(0, 8).join(' > ') : '';
  }
}
"""

FRONTEND_REQUIRED_ERRORS_JS = r"""
() => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function visible(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'&&r.bottom>=0&&r.right>=0&&r.top<=innerHeight&&r.left<=innerWidth;
  }
  function labelFor(item){
    const label=item?.querySelector('[class*="attr-label"],.ant-form-item-label,[class*="form-item-label"],label');
    return clean(label?.innerText||label?.textContent||'').replace(/^[*＊\s]+/,'').replace(/[:：]$/,'');
  }
  const errors=[];
  const nodes=[...document.querySelectorAll('.ant-form-item-explain-error,.ant-message-notice-content,.ant-notification-notice-description,[class*="explain-error"]')].filter(visible);
  for(const node of nodes){
    const text=clean(node.innerText||node.textContent);
    if(!text || !/(请输入|必填|不能为空|required|请选择)/i.test(text)) continue;
    const item=node.closest('.ant-form-item')||node.closest('[class*="form-item"]')||node.parentElement;
    errors.push({text,label:labelFor(item), itemText:clean(item?.innerText||item?.textContent||'').slice(0,220)});
  }
  const seen=new Set();
  return errors.filter(item => {
    const key=`${item.label}|${item.text}|${item.itemText}`;
    if(seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
"""

PRODUCT_ATTR_REQUIRED_ERRORS_JS = r"""
() => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function visible(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'&&r.bottom>=0&&r.right>=0&&r.top<=innerHeight&&r.left<=innerWidth;
  }
  function labelFor(item){
    const label=item?.querySelector('[class*="attr-label"],.ant-form-item-label,[class*="form-item-label"],label');
    return clean(label?.innerText||label?.textContent||'').replace(/^[*\s]+/,'').replace(/[:：]$/,'');
  }
  const root=document.querySelector('#productBasicInfo .product-attrs')||document.querySelector('.product-attrs');
  if(!root) return [];
  const errors=[];
  const nodes=[...root.querySelectorAll('.ant-form-item-explain-error,[class*="explain-error"]')].filter(visible);
  for(const node of nodes){
    const text=clean(node.innerText||node.textContent);
    if(!text || !/(请输入|请选择|必填|不能为空|required)/i.test(text)) continue;
    const item=node.closest('.attr-form-item')||node.closest('.ant-form-item')||node.closest('[class*="form-item"]')||node.parentElement;
    if(!item || !root.contains(item)) continue;
    errors.push({text,label:labelFor(item), itemText:clean(item.innerText||item.textContent||'').slice(0,220)});
  }
  const seen=new Set();
  return errors.filter(item => {
    const key=`${item.label}|${item.text}|${item.itemText}`;
    if(seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
"""

BASIC_ATTR_SET_INPUT_BY_LABEL_JS = r"""
async ({ label, value, unit }) => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function visible(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden';
  }
  function norm(s){return clean(s).replace(/^[*＊\s]+/,'').replace(/[:：]$/,'').replace(/\s+/g,'').toLowerCase()}
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  function meaningfulInputs(item){
    return [...item.querySelectorAll('textarea, input')]
      .filter(visible)
      .filter(input => (input.getAttribute('type') || '').toLowerCase() !== 'hidden')
      .filter(input => !['checkbox','radio','file'].includes((input.getAttribute('type') || '').toLowerCase()))
      .filter(input => !String(input.className || '').includes('ant-select-selection-search-input'))
      .filter(input => !input.closest('.ant-select'));
  }
  function setNativeValue(input, nextValue){
    const proto = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if(setter) setter.call(input, String(nextValue));
    else input.value = String(nextValue);
    input.dispatchEvent(new Event('input', {bubbles:true}));
    input.dispatchEvent(new Event('change', {bubbles:true}));
  }
  function readSelectValue(item){
    const select = item?.querySelector('.ant-select');
    const selection = select?.querySelector('.ant-select-selection-item');
    return clean(selection?.getAttribute('title') || selection?.innerText || selection?.textContent || '');
  }
  function hasMeaningfulSelectValue(text){
    const t=clean(text);
    if(!t) return false;
    return !/^(?:\u8bf7\u9009\u62e9|\u8bf7\u9009\u62e9\u4ea7\u54c1\u5c5e\u6027|\u8f93\u5165\u641c\u7d22\u503c|select|please select)$/i.test(t);
  }
  function labelOfItem(item){
    const labelNode=item?.querySelector('.attr-label,[class*="attr-label"],.ant-form-item-label,[class*="form-item-label"],label');
    return clean(labelNode?.innerText || labelNode?.textContent || '')
      .replace(/^[*＊\s]+/,'')
      .replace(/[:：]$/,'')
      .replace(/\u8bf7\u9009\u62e9\u4ea7\u54c1\u5c5e\u6027/g,'')
      .trim();
  }
  function labelMatches(actual, expected){
    const a=norm(actual);
    const e=norm(expected);
    return !!a && !!e && (a===e || a.includes(e) || e.includes(a));
  }
  function findAttrItem(root, expectedLabel){
    const rows=[...root.querySelectorAll('.attr-form-item')].filter(row => root.contains(row));
    for(const row of rows){
      if(labelMatches(labelOfItem(row), expectedLabel)) return row;
    }
    const labels=[...root.querySelectorAll('.attr-label,[class*="attr-label"],.ant-form-item-label,[class*="form-item-label"],label')]
      .filter(node => root.contains(node) && !node.closest('.ant-checkbox-wrapper') && !node.querySelector('input[type="checkbox"]'));
    for(const node of labels){
      if(!labelMatches(node.innerText || node.textContent || '', expectedLabel)) continue;
      const row=node.closest('.attr-form-item');
      if(row && root.contains(row)) return row;
    }
    return null;
  }
  async function setUnitSelect(item, nextUnit){
    const expected = clean(nextUnit);
    const select = item?.querySelector('.ant-select');
    if(!select) return {ok:true, skipped:true, reason:'missing_unit_select', expected};
    const before = readSelectValue(item);
    if(hasMeaningfulSelectValue(before)) return {ok:true, changed:false, skipped:true, reason:'unit_already_has_value', value:before};
    if(!expected) return {ok:true, skipped:true, reason:'empty_unit', value:before};
    const selector = select.querySelector('.ant-select-selector') || select;
    selector.scrollIntoView({block:'center', inline:'nearest'});
    selector.click();
    await sleep(160);
    const options = [...document.querySelectorAll('.ant-select-dropdown .ant-select-item-option,.ant-select-dropdown [role="option"]')]
      .filter(visible);
    const target = options.find(option => {
      const content = option.querySelector('.ant-select-item-option-content,[class*="option-content"]') || option;
      const text = clean(content.innerText || content.textContent || option.getAttribute('title') || '');
      return norm(text) === norm(expected);
    });
    if(!target) return {ok:false, error:'missing_unit_option', expected, before, options:options.map(x => clean(x.innerText || x.textContent)).filter(Boolean).slice(0,20)};
    (target.querySelector('.ant-select-item-option-content,[class*="option-content"]') || target).click();
    await sleep(180);
    const after = readSelectValue(item);
    return {ok:norm(after) === norm(expected), changed:true, before, value:after, expected};
  }
  const root=document.querySelector('#productBasicInfo .product-attrs') || document.querySelector('.product-attrs');
  if(!root) return {ok:false, error:'product_attrs_root_not_found', label, value};
  const item=findAttrItem(root, label);
  if(!item) return {ok:false, error:'product_attr_row_not_found', label, value};
  const inputs=meaningfulInputs(item);
  if(!inputs.length) return {ok:false, error:'product_attr_text_input_not_found', label, value, itemLabel:labelOfItem(item), itemText:clean(item.innerText || item.textContent || '').slice(0,220)};
  const input=inputs[0];
  input.scrollIntoView({block:'center', inline:'nearest'});
  input.focus();
  setNativeValue(input, value);
  input.blur();
  const unitResult = await setUnitSelect(item, unit);
  return {
    ok:unitResult.ok !== false,
    label:labelOfItem(item),
    value:clean(input.value || ''),
    unit:unitResult.value || '',
    fallbackUnit:clean(unit || ''),
    unitResult,
    inputClass:String(input.className || ''),
    itemText:clean(item.innerText || item.textContent || '').slice(0,220)
  };
}
"""

BASIC_ATTR_SET_PERCENT_BY_LABEL_JS = r"""
({ label, percent }) => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function visible(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden';
  }
  function norm(s){return clean(s).replace(/^[*＊\s]+/,'').replace(/[:：]$/,'').replace(/\s+/g,'').toLowerCase()}
  function setNativeValue(input, nextValue){
    const proto = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if(setter) setter.call(input, String(nextValue));
    else input.value = String(nextValue);
    try{ input.dispatchEvent(new InputEvent('input', {bubbles:true, data:String(nextValue), inputType:'insertText'})); }
    catch(_){ input.dispatchEvent(new Event('input', {bubbles:true})); }
    input.dispatchEvent(new Event('change', {bubbles:true}));
    input.dispatchEvent(new Event('blur', {bubbles:true}));
  }
  const root=document.querySelector('#productBasicInfo .product-attrs') || document.querySelector('.product-attrs');
  if(!root) return {ok:false, error:'product_attrs_root_not_found', label};
  const target=norm(label);
  const nodes=[...root.querySelectorAll('.attr-label,[class*="attr-label"],.ant-form-item-label,[class*="form-item-label"],label')]
    .filter(node => {
      const text=norm(node.innerText || node.textContent || '');
      return text && (text===target || text.includes(target) || target.includes(text));
    });
  for(const node of nodes){
    const item=node.closest('.attr-form-item') || node.closest('.ant-form-item') || node.closest('[class*="form-item"]') || node.closest('.ant-row') || node.parentElement;
    if(!item || !root.contains(item)) continue;
    const itemText=clean(item.innerText || item.textContent || '');
    if(!/%/.test(itemText)) continue;
    const inputs=[...item.querySelectorAll('input')]
      .filter(visible)
      .filter(input => (input.getAttribute('type') || '').toLowerCase() !== 'hidden')
      .filter(input => !String(input.className || '').includes('ant-select-selection-search-input'))
      .filter(input => !input.closest('.ant-select'));
    const candidates=inputs.filter(input => {
      const wrap=input.closest('.ant-input-number,[class*="input-number"]');
      const cls=String(input.className || '') + ' ' + String(wrap?.className || '');
      return !!wrap || (input.getAttribute('type') || '').toLowerCase()==='number' || /input-number|number/i.test(cls) || inputs.length === 1;
    });
    const input=candidates[0] || inputs[0] || null;
    if(!input) return {ok:false, error:'percent_input_not_found', label, itemText:itemText.slice(0,220)};
    const before=clean(input.value || '');
    if(before === String(percent)) return {ok:true, changed:false, label, value:before, itemText:itemText.slice(0,220)};
    input.scrollIntoView({block:'center', inline:'nearest'});
    input.focus();
    setNativeValue(input, percent);
    return {ok:clean(input.value || '') === String(percent), changed:true, label, before, value:clean(input.value || ''), itemText:itemText.slice(0,220)};
  }
  return {ok:false, error:'percent_attr_not_found', label};
}
"""

BASIC_ATTR_SELECT_BY_LABEL_JS = r"""
async ({ label, candidates, force }) => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function visible(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'&&r.bottom>=0&&r.right>=0&&r.top<=innerHeight&&r.left<=innerWidth;
  }
  function norm(s){
    return clean(s)
      .replace(/^[*＊\s]+/,'')
      .replace(/[:：]$/,'')
      .replace(/[\s　:：,，、()（）[\]【】\-_/]/g,'')
      .toLowerCase();
  }
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  function labelOfItem(item){
    const labelNode=item?.querySelector('.attr-label,[class*="attr-label"],.ant-form-item-label,[class*="form-item-label"],label');
    return clean(labelNode?.innerText || labelNode?.textContent || '')
      .replace(/^[*＊\s]+/,'')
      .replace(/[:：]$/,'')
      .replace(/请选择产品属性/g,'')
      .trim();
  }
  function labelMatches(actual, expected){
    const a=norm(actual);
    const e=norm(expected);
    return !!a && !!e && (a===e || a.includes(e) || e.includes(a));
  }
  function findAttrItem(root, expectedLabel){
    const rows=[...root.querySelectorAll('.attr-form-item')].filter(row => root.contains(row));
    for(const row of rows){
      if(labelMatches(labelOfItem(row), expectedLabel)) return row;
    }
    const labels=[...root.querySelectorAll('.attr-label,[class*="attr-label"],.ant-form-item-label,[class*="form-item-label"],label')]
      .filter(node => root.contains(node) && !node.closest('.ant-checkbox-wrapper') && !node.querySelector('input[type="checkbox"]'));
    for(const node of labels){
      if(!labelMatches(node.innerText || node.textContent || '', expectedLabel)) continue;
      const row=node.closest('.attr-form-item');
      if(row && root.contains(row)) return row;
    }
    return null;
  }
  function readSelectValue(item){
    const select=item?.querySelector('.ant-select');
    const values=[...select?.querySelectorAll('.ant-select-selection-item,.ant-select-selection-overflow-item,[class*="selection-item"]')||[]]
      .map(el => clean(el.getAttribute('title') || el.innerText || el.textContent || ''))
      .filter(text => text && text !== '×');
    return values.join('、');
  }
  function hasMeaningfulSelectValue(text){
    const t=clean(text);
    if(!t) return false;
    return !/^(请选择|请选择产品属性|输入搜索值|select|please select)$/i.test(t);
  }
  function optionText(option){
    const content=option.querySelector('.ant-select-item-option-content,[class*="option-content"]') || option;
    return clean(option.getAttribute('label') || option.getAttribute('title') || option.getAttribute('aria-label') || content.innerText || content.textContent || '');
  }
  function boxOf(el){
    if(!el) return null;
    const r=el.getBoundingClientRect();
    return {x:r.x,y:r.y,w:r.width,h:r.height};
  }
  function nearBox(el, box){
    if(!box) return false;
    const r=el.getBoundingClientRect();
    const cx=r.x+r.width/2;
    const xOk=cx>=box.x-120 && cx<=box.x+box.w+180;
    const yOk=r.top>=box.y-120 && r.top<=box.y+box.h+560;
    return xOk && yOk;
  }
  function chooseOption(options, expected){
    const expectedNorms=(expected||[]).map(norm).filter(Boolean);
    if(!expectedNorms.length) return null;
    let fallback=null;
    for(const option of options){
      const text=optionText(option);
      const value=norm(text);
      if(!value) continue;
      if(expectedNorms.some(item => value===item)){
        return option;
      }
      if(!fallback && expectedNorms.some(item => value.includes(item) || item.includes(value))){
        fallback=option;
      }
    }
    return fallback;
  }
  const root=document.querySelector('#productBasicInfo .product-attrs') || document.querySelector('.product-attrs');
  if(!root) return {ok:false, error:'product_attrs_root_not_found', label};
  const item=findAttrItem(root, label);
  if(!item) return {ok:false, error:'product_attr_row_not_found', label};
  const select=item.querySelector('.ant-select');
  const selector=select?.querySelector('.ant-select-selector') || select;
  if(!selector) return {ok:false, error:'product_attr_select_not_found', label, itemLabel:labelOfItem(item), itemText:clean(item.innerText || item.textContent || '').slice(0,220)};
  const before=readSelectValue(item);
  if(hasMeaningfulSelectValue(before) && !force){
    return {ok:true, skipped:true, changed:false, label:labelOfItem(item), value:before};
  }
  selector.scrollIntoView({block:'center', inline:'nearest'});
  selector.click();
  await sleep(220);
  const box=boxOf(selector);
  const dropdowns=[...document.querySelectorAll('.ant-select-dropdown,[class*="select-dropdown"]')].filter(el => visible(el) && nearBox(el, box));
  const options=[];
  for(const dropdown of dropdowns){
    options.push(...[...dropdown.querySelectorAll('.ant-select-item-option,[role="option"],.ant-select-item')].filter(visible));
  }
  const uniqueOptions=[];
  const seenKeys=new Set();
  for(const option of options){
    const text=optionText(option);
    const key=norm(text);
    if(!key || seenKeys.has(key)) continue;
    seenKeys.add(key);
    uniqueOptions.push(option);
  }
  const target=chooseOption(uniqueOptions, candidates || []);
  const seen=uniqueOptions.map(optionText).filter(Boolean);
  if(!target){
    return {ok:false, error:'product_attr_option_not_found', label:labelOfItem(item), candidates:candidates||[], seen};
  }
  const clickTarget=target.querySelector('.ant-select-item-option-content,[class*="option-content"]') || target;
  clickTarget.scrollIntoView({block:'center', inline:'nearest'});
  clickTarget.click();
  await sleep(260);
  const after=readSelectValue(item);
  const ok=hasMeaningfulSelectValue(after) && (chooseOption([{innerText:after,textContent:after,getAttribute:()=>'',querySelector:()=>null}], candidates || []) !== null || !force);
  return {ok, changed:norm(before)!==norm(after), label:labelOfItem(item), before, value:after, chosen:optionText(target), seen};
}
"""

BASIC_ATTR_VISIBLE_DROPDOWN_OPTION_POINTS_JS = r"""
({ box, candidates }) => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function norm(s){
    return clean(s)
      .replace(/^[*＊\s]+/,'')
      .replace(/[:：]$/,'')
      .replace(/[\s　:：,，、()（）[\]【】\-_/]/g,'')
      .toLowerCase();
  }
  function visible(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'&&r.bottom>=0&&r.right>=0&&r.top<=innerHeight&&r.left<=innerWidth;
  }
  function validBox(value){return value && value.ok !== false && Number.isFinite(Number(value.x)) && Number.isFinite(Number(value.y)) && Number(value.w)>0 && Number(value.h)>0}
  function nearBox(el){
    if(!validBox(box)) return false;
    const r=el.getBoundingClientRect();
    const cx=r.x+r.width/2;
    const xOk=cx>=Number(box.x)-140&&cx<=Number(box.x)+Number(box.w)+220;
    const yOk=r.top>=Number(box.y)-140&&r.top<=Number(box.y)+Number(box.h)+720;
    return xOk&&yOk;
  }
  function optionText(option){
    const content=option.querySelector('.ant-select-item-option-content,[class*="option-content"]') || option;
    return clean(option.getAttribute('label') || option.getAttribute('title') || option.getAttribute('aria-label') || content.innerText || content.textContent || '');
  }
  function optionVisibleIn(dropdown, option){
    if(!visible(option)) return false;
    const dr=dropdown.getBoundingClientRect();
    const r=option.getBoundingClientRect();
    return r.bottom>dr.top+1 && r.top<dr.bottom-1 && r.right>dr.left && r.left<dr.right;
  }
  function findScrollable(dropdown){
    const nodes=[...dropdown.querySelectorAll('.rc-virtual-list-holder,[class*="virtual-list-holder"],[class*="dropdown-menu"],[role="listbox"],div'), dropdown];
    for(const node of nodes){
      if(!node || !visible(node)) continue;
      if(node.scrollHeight > node.clientHeight + 4){
        return node;
      }
    }
    return dropdown;
  }
  function pointOf(el){
    const r=el.getBoundingClientRect();
    return {x:r.x+r.width/2, y:r.y+r.height/2};
  }
  const expected=(candidates||[]).map(norm).filter(Boolean);
  const dropdowns=[...document.querySelectorAll('.ant-select-dropdown,[class*="select-dropdown"]')].filter(el=>visible(el)&&nearBox(el));
  const seen=[];
  for(const dropdown of dropdowns){
    const scrollable=findScrollable(dropdown);
    const sr=scrollable.getBoundingClientRect();
    const options=[...dropdown.querySelectorAll('.ant-select-item-option,[role="option"],.ant-select-item')].filter(option=>optionVisibleIn(dropdown, option));
    for(const option of options){
      const text=optionText(option);
      if(text) seen.push(text);
      const value=norm(text);
      if(value && expected.some(item => value===item || value.includes(item) || item.includes(value))){
        const target=option.querySelector('.ant-select-item-option-content,[class*="option-content"]') || option;
        return {
          ok:true,
          text,
          seen:[...new Set(seen)],
          point:pointOf(target),
          dropdownBox:{x:sr.x,y:sr.y,w:sr.width,h:sr.height},
          scrollTop:scrollable.scrollTop,
          scrollHeight:scrollable.scrollHeight,
          clientHeight:scrollable.clientHeight,
          atEnd:scrollable.scrollTop + scrollable.clientHeight >= scrollable.scrollHeight - 4
        };
      }
    }
    return {
      ok:false,
      seen:[...new Set(seen)],
      dropdownBox:{x:sr.x,y:sr.y,w:sr.width,h:sr.height},
      scrollTop:scrollable.scrollTop,
      scrollHeight:scrollable.scrollHeight,
      clientHeight:scrollable.clientHeight,
      atEnd:scrollable.scrollTop + scrollable.clientHeight >= scrollable.scrollHeight - 4
    };
  }
  return {ok:false, seen:[...new Set(seen)], error:'dropdown_not_found'};
}
"""

STRICT_BASIC_ATTR_FIND_CONTROL_JS = r"""
(label) => {
  const root=document.querySelector('#productBasicInfo .product-attrs')||document.querySelector('.product-attrs');
  if(!root) return null;
  const item=findItem(root,label);
  if(!item) return null;
  const input=meaningfulInputs(item)[0];
  if(input) return input;
  return item.querySelector('.ant-select-selector,.ant-select,.ant-checkbox-wrapper')||item;
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function visible(el){if(!el) return false; const r=el.getBoundingClientRect(); const st=getComputedStyle(el); return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'}
  function meaningfulInputs(item){
    return [...item.querySelectorAll('textarea,input')]
      .filter(visible)
      .filter(input => (input.getAttribute('type') || '').toLowerCase() !== 'hidden')
      .filter(input => !['checkbox','radio','file'].includes((input.getAttribute('type') || '').toLowerCase()))
      .filter(input => !String(input.className || '').includes('ant-select-selection-search-input'))
      .filter(input => !input.closest('.ant-select'));
  }
  function normLabel(s){return clean(s).replace(/^[*＊]+/,'').replace(/[:：]$/,'').replace(/请选择产品属性/g,'').trim()}
  function findItem(scope,target){
    const labels=[...scope.querySelectorAll('[class*="attr-label"],.ant-form-item-label,[class*="form-item-label"],label')]
      .filter(el=>!el.closest('.ant-checkbox-wrapper')&&!el.querySelector('input[type="checkbox"]'));
    for(const node of labels){
      const actual=normLabel(node.innerText||node.textContent);
      if(!(actual===target || actual.includes(target) || target.includes(actual))) continue;
      const item=node.closest('.attr-form-item')||node.closest('.ant-form-item')||node.closest('[class*="form-item"]')||node.closest('.ant-row')||node.parentElement;
      if(item&&scope.contains(item)) return item;
    }
    return null;
  }
}
"""

STRICT_GET_BASIC_ATTR_SELECT_BOX_BY_LABEL_JS = r"""
(label) => {
  const root=document.querySelector('#productBasicInfo .product-attrs')||document.querySelector('.product-attrs');
  if(!root) return {ok:false,error:'product_attrs_root_not_found'};
  const item=findItem(root,label);
  const itemText=clean(item?.innerText||item?.textContent||'');
  if(meaningfulInputs(item).length && !/%/.test(itemText) && !clean(label).includes('成分')) return {ok:false,error:'input_field_has_text_input'};
  const select=item?.querySelector('.ant-select-selector,.ant-select');
  if(!select) return {ok:false,error:'select_not_found'};
  select.scrollIntoView({block:'center',inline:'center'});
  const r=select.getBoundingClientRect();
  return {ok:true,label,x:r.x,y:r.y,w:r.width,h:r.height};
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function visible(el){if(!el) return false; const r=el.getBoundingClientRect(); const st=getComputedStyle(el); return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'}
  function meaningfulInputs(item){
    if(!item) return [];
    return [...item.querySelectorAll('textarea,input')]
      .filter(visible)
      .filter(input => (input.getAttribute('type') || '').toLowerCase() !== 'hidden')
      .filter(input => !['checkbox','radio','file'].includes((input.getAttribute('type') || '').toLowerCase()))
      .filter(input => !String(input.className || '').includes('ant-select-selection-search-input'))
      .filter(input => !input.closest('.ant-select'));
  }
  function normLabel(s){return clean(s).replace(/^[*＊]+/,'').replace(/[:：]$/,'').replace(/请选择产品属性/g,'').trim()}
  function findItem(scope,target){
    const labels=[...scope.querySelectorAll('[class*="attr-label"],.ant-form-item-label,[class*="form-item-label"],label')]
      .filter(el=>!el.closest('.ant-checkbox-wrapper')&&!el.querySelector('input[type="checkbox"]'));
    for(const node of labels){
      const actual=normLabel(node.innerText||node.textContent);
      if(!(actual===target || actual.includes(target) || target.includes(actual))) continue;
      const item=node.closest('.attr-form-item')||node.closest('.ant-form-item')||node.closest('[class*="form-item"]')||node.closest('.ant-row')||node.parentElement;
      if(item&&scope.contains(item)) return item;
    }
    return null;
  }
}
"""

STRICT_GET_BASIC_ATTR_SELECT_OPTION_POINTS_BY_LABEL_JS = r"""
({target, box}) => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function norm(s){return clean(s).replace(/[\s　:：,，、()（）[\]【】]/g,'').toLowerCase()}
  function visible(el){const r=el.getBoundingClientRect();const st=getComputedStyle(el);return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'&&r.bottom>=0&&r.right>=0&&r.top<=innerHeight&&r.left<=innerWidth}
  function validBox(value){return value && value.ok !== false && Number.isFinite(Number(value.x)) && Number.isFinite(Number(value.y)) && Number(value.w)>0 && Number(value.h)>0}
  function nearBox(el){
    if(!validBox(box)) return false;
    const r=el.getBoundingClientRect();
    const cx=r.x+r.width/2;
    const xOk=cx>=Number(box.x)-80&&cx<=Number(box.x)+Number(box.w)+120;
    const yOk=r.top>=Number(box.y)-80&&r.top<=Number(box.y)+Number(box.h)+520;
    return xOk&&yOk;
  }
  if(!validBox(box)) return {ok:false,seen:[],error:'missing_select_box'};
  const targetNorm=norm(target), seen=[];
  const dropdowns=[...document.querySelectorAll('.ant-select-dropdown,[class*="select-dropdown"]')].filter(el=>visible(el)&&nearBox(el));
  for(const dd of dropdowns){
    const options=[...dd.querySelectorAll('.ant-select-item-option,[role="option"],.ant-select-item')].filter(visible);
    for(const option of options){
      const txt=clean(option.getAttribute('label')||option.getAttribute('aria-label')||option.innerText||option.textContent);
      if(txt) seen.push(txt);
      if(norm(txt)===targetNorm){
        option.scrollIntoView({block:'center',inline:'center'});
        const r=option.getBoundingClientRect();
        return {ok:true,text:txt,seen:[...new Set(seen)],points:[{x:r.x+r.width/2,y:r.y+r.height/2}]};
      }
    }
  }
  return {ok:false,seen:[...new Set(seen)]};
}
"""

STRICT_GET_BASIC_ATTR_VALUE_BY_LABEL_JS = r"""
(label) => {
  const root=document.querySelector('#productBasicInfo .product-attrs')||document.querySelector('.product-attrs');
  if(!root) return {ok:false,value:'',error:'product_attrs_root_not_found'};
  const item=findItem(root,label);
  if(!item) return {ok:false,value:'',error:'field_not_found'};
  const itemText=clean(item.innerText||item.textContent||'');
  const selectValue=[...item.querySelectorAll('.ant-select-selection-item,.ant-select-selection-overflow-item,[class*="selection-item"]')]
    .map(el=>clean(el.innerText||el.textContent)).filter(v=>v&&v!=='×'&&!/^请选择/.test(v)).join('、');
  const textInputs=meaningfulInputs(item);
  if(textInputs.length && !/%/.test(itemText) && !clean(label).includes('成分')){
    const inputValue=textInputs.map(input=>clean(input.value||'')).filter(Boolean).join('、');
    return {ok:true,value:inputValue};
  }
  const value=selectValue||textInputs.map(input=>clean(input.value||'')).filter(Boolean).join('、')||clean(item.querySelector('input:not([type="hidden"]),textarea')?.value||'');
  return {ok:true,value};
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function visible(el){if(!el) return false; const r=el.getBoundingClientRect(); const st=getComputedStyle(el); return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'}
  function meaningfulInputs(item){
    return [...item.querySelectorAll('textarea,input')]
      .filter(visible)
      .filter(input => (input.getAttribute('type') || '').toLowerCase() !== 'hidden')
      .filter(input => !['checkbox','radio','file'].includes((input.getAttribute('type') || '').toLowerCase()))
      .filter(input => !String(input.className || '').includes('ant-select-selection-search-input'))
      .filter(input => !input.closest('.ant-select'));
  }
  function normLabel(s){return clean(s).replace(/^[*＊]+/,'').replace(/[:：]$/,'').replace(/请选择产品属性/g,'').trim()}
  function findItem(scope,target){
    const labels=[...scope.querySelectorAll('[class*="attr-label"],.ant-form-item-label,[class*="form-item-label"],label')]
      .filter(el=>!el.closest('.ant-checkbox-wrapper')&&!el.querySelector('input[type="checkbox"]'));
    for(const node of labels){
      const actual=normLabel(node.innerText||node.textContent);
      if(!(actual===target || actual.includes(target) || target.includes(actual))) continue;
      const item=node.closest('.attr-form-item')||node.closest('.ant-form-item')||node.closest('[class*="form-item"]')||node.closest('.ant-row')||node.parentElement;
      if(item&&scope.contains(item)) return item;
    }
    return null;
  }
}
"""

BASIC_ATTR_SYNC_CONTROL_BY_LABEL_JS = r"""
(label) => {
  const root=document.querySelector('#productBasicInfo .product-attrs')||document.querySelector('.product-attrs');
  if(!root) return {ok:false,error:'product_attrs_root_not_found'};
  const item=findItem(root,label);
  if(!item) return {ok:false,error:'field_not_found'};
  const events=[];
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function visible(el){if(!el) return false; const r=el.getBoundingClientRect(); const st=getComputedStyle(el); return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'}
  function fire(el,type){
    try{
      if(type==='input'){
        try{ el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:el.value||''})); }
        catch(_){ el.dispatchEvent(new Event('input',{bubbles:true})); }
      }else{
        el.dispatchEvent(new Event(type,{bubbles:true}));
      }
      events.push(type);
    }catch(_){}
  }
  function meaningfulInputs(row){
    return [...row.querySelectorAll('textarea,input')]
      .filter(visible)
      .filter(input => (input.getAttribute('type') || '').toLowerCase() !== 'hidden')
      .filter(input => !['checkbox','radio','file'].includes((input.getAttribute('type') || '').toLowerCase()))
      .filter(input => !String(input.className || '').includes('ant-select-selection-search-input'))
      .filter(input => !input.closest('.ant-select'));
  }
  function readValue(row){
    const selectValue=[...row.querySelectorAll('.ant-select-selection-item,.ant-select-selection-overflow-item,[class*="selection-item"]')]
      .map(el=>clean(el.innerText||el.textContent)).filter(v=>v&&v!=='x'&&v!=='脳'&&!/^请选择/.test(v)).join('、');
    const inputValue=meaningfulInputs(row).map(input=>clean(input.value||'')).filter(Boolean).join('、');
    return selectValue || inputValue || '';
  }
  function normLabel(s){return clean(s).replace(/^[*\s]+/,'').replace(/[:：]$/,'').replace(/请选择产品属性/g,'').trim()}
  function findItem(scope,target){
    const labels=[...scope.querySelectorAll('[class*="attr-label"],.ant-form-item-label,[class*="form-item-label"],label')]
      .filter(el=>!el.closest('.ant-checkbox-wrapper')&&!el.querySelector('input[type="checkbox"]'));
    for(const node of labels){
      const actual=normLabel(node.innerText||node.textContent);
      if(!(actual===target || actual.includes(target) || target.includes(actual))) continue;
      const row=node.closest('.attr-form-item')||node.closest('.ant-form-item')||node.closest('[class*="form-item"]')||node.closest('.ant-row')||node.parentElement;
      if(row&&scope.contains(row)) return row;
    }
    return null;
  }
  for(const input of meaningfulInputs(item)){
    input.focus();
    fire(input,'input');
    fire(input,'change');
    input.blur();
    fire(input,'blur');
  }
  for(const el of item.querySelectorAll('.ant-select-selector,.ant-select-selection-item,.ant-select-selection-search-input')){
    fire(el,'change');
    fire(el,'blur');
  }
  return {ok:true,label:normLabel(label),value:readValue(item),events};
}
"""

STRICT_GET_BASIC_ATTR_CHECKBOX_OPTIONS_JS = r"""
(label) => {
  const root=document.querySelector('#productBasicInfo .product-attrs')||document.querySelector('.product-attrs');
  if(!root) return {ok:false,options:[],error:'product_attrs_root_not_found'};
  const item=findItem(root,label);
  if(!item) return {ok:false,options:[],error:'field_not_found'};
  const options=[...item.querySelectorAll('.ant-checkbox-wrapper,label')].filter(el=>el.querySelector('input[type="checkbox"],.ant-checkbox')).map(el=>clean(el.innerText||el.textContent).replace(/^[*＊]/,'').trim()).filter(Boolean);
  return {ok:true,options:[...new Set(options)]};
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function normLabel(s){return clean(s).replace(/^[*＊]+/,'').replace(/[:：]$/,'').trim()}
  function findItem(scope,target){
    const labels=[...scope.querySelectorAll('[class*="attr-label"],.ant-form-item-label,[class*="form-item-label"],label')].filter(el=>!el.closest('.ant-checkbox-wrapper')&&!el.querySelector('input[type="checkbox"]'));
    for(const node of labels){
      const actual=normLabel(node.innerText||node.textContent);
      if(!(actual===target || actual.includes(target) || target.includes(actual))) continue;
      const item=node.closest('.attr-form-item')||node.closest('.ant-form-item')||node.closest('[class*="form-item"]')||node.closest('.ant-row')||node.parentElement;
      if(item&&scope.contains(item)) return item;
    }
    return null;
  }
}
"""

STRICT_CLICK_BASIC_ATTR_CHECKBOX_BY_LABEL_JS = r"""
({label, value}) => {
  const root=document.querySelector('#productBasicInfo .product-attrs')||document.querySelector('.product-attrs');
  if(!root) return false;
  const item=findItem(root,label);
  if(!item) return false;
  const target=norm(value);
  const labels=[...item.querySelectorAll('.ant-checkbox-wrapper,label')].filter(el=>el.querySelector('input[type="checkbox"],.ant-checkbox'));
  const found=labels.find(el=>norm(el.innerText||el.textContent)===target);
  if(!found) return false;
  const input=found.querySelector('input[type="checkbox"]');
  if(input&&input.checked) return true;
  found.scrollIntoView({block:'center',inline:'center'});
  found.dispatchEvent(new MouseEvent('mousemove',{bubbles:true}));
  found.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));
  found.click();
  found.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
  return true;
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function norm(s){return clean(s).replace(/^[*＊]/,'').replace(/[:：]$/,'').replace(/[\s　:：,，、()（）[\]【】]/g,'').toLowerCase()}
  function normLabel(s){return clean(s).replace(/^[*＊]+/,'').replace(/[:：]$/,'').trim()}
  function findItem(scope,target){
    const labels=[...scope.querySelectorAll('[class*="attr-label"],.ant-form-item-label,[class*="form-item-label"],label')].filter(el=>!el.closest('.ant-checkbox-wrapper')&&!el.querySelector('input[type="checkbox"]'));
    for(const node of labels){
      const actual=normLabel(node.innerText||node.textContent);
      if(!(actual===target || actual.includes(target) || target.includes(actual))) continue;
      const item=node.closest('.attr-form-item')||node.closest('.ant-form-item')||node.closest('[class*="form-item"]')||node.closest('.ant-row')||node.parentElement;
      if(item&&scope.contains(item)) return item;
    }
    return null;
  }
}
"""

STRICT_FILL_BASIC_MATERIAL_PERCENT_BY_LABEL_JS = str(BASE.get("FILL_BASIC_MATERIAL_PERCENT_BY_LABEL_JS") or "").replace(
    "const roots=[document.querySelector('#productBasicInfo'), ...document.querySelectorAll('.form-card'), document.body].filter(Boolean);",
    "const attrRoot=document.querySelector('#productBasicInfo .product-attrs')||document.querySelector('.product-attrs'); const roots=attrRoot ? [attrRoot] : [];",
)

if isinstance(BASE.get("LEGACY"), dict):
    BASE["LEGACY"]["BASIC_ATTR_SCAN_JS"] = PATCHED_BASIC_ATTR_SCAN_JS
    BASE["LEGACY"]["BASIC_ATTR_FIND_CONTROL_JS"] = STRICT_BASIC_ATTR_FIND_CONTROL_JS
    BASE["LEGACY"]["BASIC_ATTR_CLICK_CHECKBOX_JS"] = STRICT_CLICK_BASIC_ATTR_CHECKBOX_BY_LABEL_JS
    BASE["LEGACY"]["GET_BASIC_ATTR_SELECT_BOX_BY_LABEL_JS"] = STRICT_GET_BASIC_ATTR_SELECT_BOX_BY_LABEL_JS
    BASE["LEGACY"]["GET_BASIC_ATTR_SELECT_OPTION_POINTS_BY_LABEL_JS"] = STRICT_GET_BASIC_ATTR_SELECT_OPTION_POINTS_BY_LABEL_JS
    BASE["LEGACY"]["GET_BASIC_ATTR_VALUE_BY_LABEL_JS"] = STRICT_GET_BASIC_ATTR_VALUE_BY_LABEL_JS
    BASE["LEGACY"]["GET_BASIC_ATTR_CHECKBOX_OPTIONS_JS"] = STRICT_GET_BASIC_ATTR_CHECKBOX_OPTIONS_JS
    BASE["LEGACY"]["CLICK_BASIC_ATTR_CHECKBOX_BY_LABEL_JS"] = STRICT_CLICK_BASIC_ATTR_CHECKBOX_BY_LABEL_JS
    BASE["LEGACY"]["FILL_BASIC_MATERIAL_PERCENT_BY_LABEL_JS"] = STRICT_FILL_BASIC_MATERIAL_PERCENT_BY_LABEL_JS
BASE["BASIC_ATTR_FIND_CONTROL_JS"] = STRICT_BASIC_ATTR_FIND_CONTROL_JS
BASE["BASIC_ATTR_CLICK_CHECKBOX_JS"] = STRICT_CLICK_BASIC_ATTR_CHECKBOX_BY_LABEL_JS
BASE["GET_BASIC_ATTR_SELECT_BOX_BY_LABEL_JS"] = STRICT_GET_BASIC_ATTR_SELECT_BOX_BY_LABEL_JS
BASE["GET_BASIC_ATTR_SELECT_OPTION_POINTS_BY_LABEL_JS"] = STRICT_GET_BASIC_ATTR_SELECT_OPTION_POINTS_BY_LABEL_JS
BASE["GET_BASIC_ATTR_VALUE_BY_LABEL_JS"] = STRICT_GET_BASIC_ATTR_VALUE_BY_LABEL_JS
BASE["GET_BASIC_ATTR_CHECKBOX_OPTIONS_JS"] = STRICT_GET_BASIC_ATTR_CHECKBOX_OPTIONS_JS
BASE["CLICK_BASIC_ATTR_CHECKBOX_BY_LABEL_JS"] = STRICT_CLICK_BASIC_ATTR_CHECKBOX_BY_LABEL_JS
BASE["FILL_BASIC_MATERIAL_PERCENT_BY_LABEL_JS"] = STRICT_FILL_BASIC_MATERIAL_PERCENT_BY_LABEL_JS
BASE["GET_WAREHOUSE_SELECTED_STATE_JS"] = WAREHOUSE_SELECTED_STATE_WITH_CHECKBOX_JS
IMAGE_EXTS = set(BASE.get("IMAGE_EXTS") or {".jpg", ".jpeg", ".png", ".webp", ".bmp"})
PIPELINE_CONFIG_PATH = Path(BASE.get("PIPELINE_CONFIG_PATH", APP_DIR / "work" / "state" / "automation-config.json"))
LAOZHANG_API_CONFIG_PATH = Path(
    (BASE.get("LEGACY") or {}).get("API_CONFIG_PATH", APP_DIR / "work" / "state" / "laozhang-api.json")
)
STOP_EVENT = threading.Event()
ACTIVE_ROBOTS: "weakref.WeakSet[Any]" = weakref.WeakSet()
ACTIVE_ROBOTS_LOCK = threading.RLock()
ACTIVE_CONTROL_ROOTS: "weakref.WeakSet[Any]" = weakref.WeakSet()
ACTIVE_CONTROL_ROOTS_LOCK = threading.RLock()
APP_EXITING = False
INSTANCE_LOCK_HANDLE: Any | None = None
CLEANUP_DONE = False
CLEANUP_LOCK = threading.RLock()
PRODUCT_ATTR_SESSION_CACHE_PATH = APP_DIR / "work" / "state" / f"product-attr-session-cache-{os.getpid()}.json"
PRODUCT_ATTR_SESSION_CACHE_LOCK = threading.RLock()
PRODUCT_ATTR_SESSION_CACHE: dict[str, Any] = {
    "version": 1,
    "pid": os.getpid(),
    "createdAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    "categories": {},
}


class StopRequested(BaseException):
    pass


_ORIGINAL_DXM_TEMU_ROBOT_CLASS = BASE["LEGACY"]["DxmTemuRobot"]


def _register_active_robot(robot: Any) -> None:
    with ACTIVE_ROBOTS_LOCK:
        ACTIVE_ROBOTS.add(robot)


def _unregister_active_robot(robot: Any) -> None:
    with ACTIVE_ROBOTS_LOCK:
        try:
            ACTIVE_ROBOTS.discard(robot)
        except Exception:
            pass


def _active_robots_snapshot() -> list[Any]:
    with ACTIVE_ROBOTS_LOCK:
        return list(ACTIVE_ROBOTS)


def _register_control_root(root: Any) -> None:
    with ACTIVE_CONTROL_ROOTS_LOCK:
        ACTIVE_CONTROL_ROOTS.add(root)


def _active_control_roots_snapshot() -> list[Any]:
    with ACTIVE_CONTROL_ROOTS_LOCK:
        return list(ACTIVE_CONTROL_ROOTS)


def _clear_stop_request() -> None:
    STOP_EVENT.clear()


def _check_stop(context: str = "") -> None:
    if STOP_EVENT.is_set():
        suffix = f"：{context}" if context else ""
        raise StopRequested(f"已停止当前任务{suffix}")


def _stop_requested_as_runtime(context: str = "") -> None:
    try:
        _check_stop(context)
    except StopRequested as exc:
        raise RuntimeError(str(exc) or "已停止当前任务") from None


def _cleanup_child_process_tree(timeout: float = 1.5) -> None:
    try:
        import psutil
    except Exception as exc:
        _log("WARN", "psutil 不可用，无法清理子进程树", error=_safe_error_text(exc))
        return
    try:
        current = psutil.Process(os.getpid())
        children = current.children(recursive=True)
    except Exception as exc:
        _log("WARN", "读取子进程树失败", error=_safe_error_text(exc))
        return
    if not children:
        return
    for child in children:
        try:
            child.terminate()
        except Exception:
            pass
    gone, alive = psutil.wait_procs(children, timeout=timeout)
    for child in alive:
        try:
            child.kill()
        except Exception:
            pass
    if alive:
        _log("WARN", "已强制清理残留子进程", count=len(alive), pids="|".join(str(item.pid) for item in alive))
    else:
        _log("OK", "已清理机器人子进程", count=len(children))


def _cleanup_runtime_resources(*, kill_children: bool = True) -> None:
    if kill_children:
        _cleanup_child_process_tree()


class StoppableDxmTemuRobot(_ORIGINAL_DXM_TEMU_ROBOT_CLASS):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _check_stop("创建机器人")
        super().__init__(*args, **kwargs)
        _register_active_robot(self)

    def close(self) -> None:
        try:
            close = getattr(super(), "close", None)
            if callable(close):
                close()
        finally:
            _unregister_active_robot(self)


BASE["LEGACY"]["DxmTemuRobot"] = StoppableDxmTemuRobot

PRODUCT_INFO_FIND_ACTION_POINT_JS = r"""
async ({ labels, exact }) => {
  const root = findModuleRoot('\u4ea7\u54c1\u4fe1\u606f');
  if (!root) return { ok: false, error: 'product info module not found', seen: [] };
  const anchor = findAnchor(root, '\u4ea7\u54c1\u8f6e\u64ad\u56fe') || findAnchor(root, '\u4ea7\u54c1\u7d20\u6750\u56fe');
  if (anchor) {
    try { anchor.scrollIntoView({ block: 'center', inline: 'center' }); } catch (_) { anchor.scrollIntoView(); }
    await sleep(500);
  }
  try {
    root.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true }));
    for (const img of [...root.querySelectorAll('img')].slice(0, 12)) {
      img.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true }));
      img.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, cancelable: true }));
    }
  } catch (_) {}
  await sleep(180);

  const seen = [];
  const scored = [];
  const nodeSet = new Set([...root.querySelectorAll('button,a,span,div,li,[role="button"]')]);
  for (const el of document.querySelectorAll('button,a,span,div,li,[role="button"]')) {
    if (isNearProductCarousel(el, root, anchor)) nodeSet.add(el);
  }
  const nodes = [...nodeSet].filter(hasBox);
  for (const el of nodes) {
    const txt = labelText(el);
    if (!txt) continue;
    if (txt.length < 80) seen.push(txt);
    for (const label of labels || []) {
      const ok = exact ? txt === label : txt.includes(label);
      if (!ok) continue;
      if (!isLikelyClickableAction(el, txt, label)) continue;
      const r = el.getBoundingClientRect();
      const inRootScore = root.contains(el) ? 0 : 2;
      const nearScore = anchor ? Math.min(8, Math.abs(centerY(el) - centerY(anchor)) / 80) : 0;
      const tagScore = ['BUTTON','A','LI'].includes(el.tagName) ? 0 : 1;
      const lengthScore = Math.abs(txt.length - label.length);
      scored.push({ el, label, text: txt, inRootScore, nearScore, tagScore, lengthScore, area: r.width * r.height });
    }
  }
  scored.sort((a, b) => a.inRootScore - b.inRootScore || a.nearScore - b.nearScore || a.tagScore - b.tagScore || a.lengthScore - b.lengthScore || a.area - b.area);
  const best = scored[0];
  if (!best) return { ok: false, seen: [...new Set(seen)].slice(0, 40) };
  try { best.el.scrollIntoView({ block: 'center', inline: 'center' }); } catch (_) { best.el.scrollIntoView(); }
  await sleep(180);
  const r = best.el.getBoundingClientRect();
  return { ok: true, label: best.label, text: best.text, x: r.x + r.width / 2, y: r.y + r.height / 2 };

  function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
  function clean(s) { return (s || '').replace(/[\n\r\t]+/g, ' ').replace(/\s+/g, ' ').trim(); }
  function labelText(el) {
    return clean([
      el.innerText || el.textContent || '',
      el.getAttribute('title') || '',
      el.getAttribute('aria-label') || '',
      el.getAttribute('data-original-title') || ''
    ].join(' '));
  }
  function hasBox(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden';
  }
  function centerY(el) {
    const r = el.getBoundingClientRect();
    return r.top + r.height / 2;
  }
  function isLikelyClickableAction(el, txt, label) {
    const cls = String(el.className || '');
    if (txt === label) return true;
    if (txt.length <= label.length + 16) return true;
    if (['BUTTON','A','LI'].includes(el.tagName) && txt.length <= label.length + 40) return true;
    if (/(trigger|btn|button|action|dropdown)/i.test(cls) && txt.length <= label.length + 40) return true;
    return false;
  }
  function isNearProductCarousel(el, root, anchor) {
    if (!hasBox(el)) return false;
    if (root.contains(el)) return true;
    if (!anchor) return false;
    const er = el.getBoundingClientRect();
    const ar = anchor.getBoundingClientRect();
    const y = er.top + er.height / 2;
    return y >= ar.top - 260 && y <= ar.bottom + 520 && er.left >= ar.left - 180 && er.left <= ar.right + 720;
  }
  function text(el) { return clean(el && (el.innerText || el.textContent)); }
  function findAnchor(scope, label) {
    const candidates = [...scope.querySelectorAll('label,span,div,p,h4')].filter(hasBox)
      .map(el => ({ el, txt: text(el) }))
      .filter(item => item.txt === label || (item.txt.includes(label) && item.txt.length <= label.length + 120))
      .sort((a, b) => a.txt.length - b.txt.length);
    return candidates.length ? candidates[0].el : null;
  }
  function findModuleRoot(name) {
    const heads = [...document.querySelectorAll('h4, .form-card-title, .form-card-header, [class*="form-card-title"], [class*="form-card-header"]')];
    const head = heads.find(h => text(h).includes(name));
    return head ? (head.closest('.form-card') || head.closest('[class*="form-card"]') || head.parentElement) : null;
  }
}
"""

PRODUCT_INFO_IMAGE_STATE_JS = r"""
() => {
  const root = findModuleRoot('\u4ea7\u54c1\u4fe1\u606f');
  if (!root) return { ok: false, error: 'product info module not found', imageCount: 0, selectedCount: null, text: '' };
  const txt = text(root);
  const match = txt.match(/\u5df2\u7ecf\u9009\u7528\u4e86\s*(\d+)\s*\u5f20/);
  const selectedCount = match ? Number(match[1]) : null;
  const badUrl = /(favicon|logo|iconfont|sprite|loading|blank|placeholder|rightBtnIcon|otherIcon|assets\/.*icon|assets\/.*Icon)/i;
  const imgs = [...root.querySelectorAll('img')].filter(img => {
    const r = img.getBoundingClientRect();
    const url = String(img.currentSrc || img.src || '');
    return r.width >= 80 && r.height >= 80 && !badUrl.test(url);
  });
  return { ok: true, imageCount: imgs.length, selectedCount, text: txt.slice(0, 500) };

  function clean(s) { return (s || '').replace(/[\n\r\t]+/g, ' ').replace(/\s+/g, ' ').trim(); }
  function text(el) { return clean(el && (el.innerText || el.textContent)); }
  function findModuleRoot(name) {
    const heads = [...document.querySelectorAll('h4, .form-card-title, .form-card-header, [class*="form-card-title"], [class*="form-card-header"]')];
    const head = heads.find(h => text(h).includes(name));
    return head ? (head.closest('.form-card') || head.closest('[class*="form-card"]') || head.parentElement) : null;
  }
}
"""

PRODUCT_INFO_CONFIRM_IF_ANY_JS = r"""
async () => {
  const labels = ['\u786e\u5b9a', '\u786e\u8ba4', '\u5220\u9664', '\u662f', 'OK', 'Ok', 'ok'];
  const scopes = [...document.querySelectorAll('.ant-popover,.ant-modal,.ant-modal-wrap')].filter(visible);
  for (const scope of scopes) {
    const scopeText = normalizedText(scope);
    if (scopeText && !/清空.*图片|清空全部图片/.test(scopeText)) continue;
    const buttons = [...scope.querySelectorAll('button,a,[role="button"]')].filter(visible);
    const button = buttons.find(el => {
      const raw = text(el);
      const normalized = normalizedText(el);
      return labels.some(label => raw === label || raw.includes(label) || normalized === normalize(label) || normalized.includes(normalize(label)));
    });
    if (button) {
      clickElement(button);
      await sleep(260);
      return { ok: true, text: text(button) };
    }
  }
  return { ok: false };

  function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
  function clean(s) { return (s || '').replace(/[\n\r\t]+/g, ' ').replace(/\s+/g, ' ').trim(); }
  function text(el) { return clean(el && (el.innerText || el.textContent)); }
  function normalize(s) { return clean(s).replace(/\s+/g, ''); }
  function normalizedText(el) { return normalize(el && (el.innerText || el.textContent)); }
  function visible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden';
  }
  function clickElement(el) {
    el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true }));
    el.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, cancelable: true }));
    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
    el.click();
  }
}
"""

PRODUCT_DESC_CLICK_MENU_ITEM_JS = r"""
async ({ labels, exact, click }) => {
  const scopes = [
    ...document.querySelectorAll('.ant-dropdown,.ant-popover,.ant-modal,.ant-modal-wrap,[role="menu"]')
  ].filter(visible);
  const seen = [];
  const scored = [];
  for (const scope of scopes) {
    const nodes = [...scope.querySelectorAll('button,a,span,div,li,[role="button"],[role="menuitem"]')];
    for (const el of nodes) {
      const txt = text(el);
      if (!txt) continue;
      if (txt.length < 80) seen.push(txt);
      for (const label of labels || []) {
        const ok = exact ? normalize(txt) === normalize(label) : normalize(txt).includes(normalize(label));
        if (!ok) continue;
        const r = el.getBoundingClientRect();
        const tagScore = ['BUTTON','A','LI'].includes(el.tagName) ? 0 : 1;
        const lengthScore = Math.abs(normalize(txt).length - normalize(label).length);
        const visibleScore = visible(el) ? 0 : 1;
        scored.push({ el, label, text: txt, tagScore, lengthScore, visibleScore, area: r.width * r.height });
      }
    }
  }
  scored.sort((a, b) => a.tagScore - b.tagScore || a.lengthScore - b.lengthScore || a.visibleScore - b.visibleScore || a.area - b.area);
  const best = scored[0];
  if (!best) {
    const fallback = fallbackMenuPoint(scopes, labels || []);
    if (fallback) {
      const target = document.elementFromPoint(fallback.x, fallback.y) || fallback.scope;
      target.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true, clientX: fallback.x, clientY: fallback.y }));
      target.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, cancelable: true, clientX: fallback.x, clientY: fallback.y }));
      if (click !== false) {
        target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, clientX: fallback.x, clientY: fallback.y }));
        target.click();
        target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, clientX: fallback.x, clientY: fallback.y }));
      }
      await sleep(260);
      return { ok: true, label: fallback.label, text: fallback.text, x: fallback.x, y: fallback.y, clicked: click !== false, fallback: true };
    }
    return { ok: false, seen: [...new Set(seen)].slice(0, 40) };
  }
  try { best.el.scrollIntoView({ block: 'center', inline: 'center' }); } catch (_) { best.el.scrollIntoView(); }
  await sleep(120);
  const r = best.el.getBoundingClientRect();
  best.el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true }));
  best.el.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, cancelable: true }));
  if (click !== false) {
    best.el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
    best.el.click();
    best.el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
  }
  await sleep(260);
  return { ok: true, label: best.label, text: best.text, x: r.x + r.width / 2, y: r.y + r.height / 2, clicked: click !== false };

  function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
  function clean(s) { return (s || '').replace(/[\n\r\t]+/g, ' ').replace(/\s+/g, ' ').trim(); }
  function normalize(s) { return clean(s).replace(/\s+/g, ''); }
  function text(el) { return clean(el && (el.innerText || el.textContent)); }
  function fallbackMenuPoint(scopes, labels) {
    const orders = [
      ['文字翻译','批量图片翻译','批量改图片尺寸','批量编辑','图片白底','批量传图','批量压缩图片','清空描述'],
      ['清空图片模块','清空文字模块'],
      ['本地上传','空间图片','网络图片','引用采集图片'],
      ['本地图片','空间图片','网络图片','引用采集图片']
    ];
    for (const scope of scopes) {
      const cls = String(scope.className || '');
      if (!/dropdown|popover|menu/i.test(cls) && scope.getAttribute('role') !== 'menu') continue;
      const scopeText = normalize(text(scope));
      const r = scope.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      for (const label of labels) {
        const wanted = normalize(label);
        if (!scopeText.includes(wanted)) continue;
        const order = orders.find(items => items.some(item => normalize(item) === wanted));
        if (!order) continue;
        const index = order.findIndex(item => normalize(item) === wanted);
        if (index < 0) continue;
        const rowHeight = r.height / order.length;
        return {
          scope,
          label,
          text: text(scope),
          x: Math.min(r.right - 8, Math.max(r.left + 8, r.left + r.width / 2)),
          y: Math.min(r.bottom - 8, Math.max(r.top + 8, r.top + rowHeight * (index + 0.5)))
        };
      }
    }
    return null;
  }
  function visible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden'
      && r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
  }
}
"""

PRODUCT_DESC_DELETE_IMAGE_MODULES_JS = r"""
async () => {
  const wrap = [...document.querySelectorAll('.ant-modal-wrap.full-modal__dxm')].find(visible);
  if (!wrap) return { ok: false, deleted: 0, before: 0, after: 0, error: 'description editor not open' };
  const before = imageItems().length;
  const deleted = [];
  const failed = [];
  for (let i = 0; i < 40; i += 1) {
    const item = imageItems()[0];
    if (!item) break;
    const itemText = text(item);
    try {
      item.scrollIntoView({ block: 'center', inline: 'center' });
      await sleep(120);
      hover(item);
      await sleep(180);
      const del = findDelete(item);
      if (del) {
        clickElement(del);
      } else {
        const r = item.getBoundingClientRect();
        clickAt(r.right - 14, r.top + r.height / 2);
      }
      await sleep(300);
      await clickConfirmIfAny();
      await sleep(250);
      deleted.push({ text: itemText });
    } catch (error) {
      failed.push({ text: itemText, error: String(error && error.message || error) });
      break;
    }
  }
  const after = imageItems().length;
  return { ok: failed.length === 0 && after === 0, deleted: deleted.length, before, after, failed };

  function imageItems() {
    const using = wrap.querySelector('.using-modules') || wrap;
    return [...using.querySelectorAll('.using-item,.sortable-item')]
      .filter(item => normalize(text(item)) === '\u56fe\u7247');
  }
  function findDelete(scope) {
    const candidates = [...scope.querySelectorAll('.icon_delete,[class*="icon_delete"],[class*="delete"],[title*="\u5220\u9664"],[aria-label*="\u5220\u9664"]')];
    return candidates.find(Boolean) || null;
  }
  function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
  function clean(s) { return (s || '').replace(/[\n\r\t]+/g, ' ').replace(/\s+/g, ' ').trim(); }
  function normalize(s) { return clean(s).replace(/\s+/g, ''); }
  function text(el) { return clean(el && (el.innerText || el.textContent)); }
  function visible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden'
      && r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
  }
  function hover(el) {
    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2;
    const y = r.top + r.height / 2;
    el.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
    el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
    el.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
  }
  function clickElement(el) {
    const r = el.getBoundingClientRect();
    const x = r.width > 0 ? r.left + r.width / 2 : 0;
    const y = r.height > 0 ? r.top + r.height / 2 : 0;
    el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
    el.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
    el.click();
    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
  }
  function clickAt(x, y) {
    const target = document.elementFromPoint(x, y);
    if (!target) throw new Error('delete target not found at point');
    target.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
    target.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
    target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
    target.click();
    target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
  }
  async function clickConfirmIfAny() {
    const labels = ['\u786e\u5b9a', '\u786e\u8ba4', '\u5220\u9664', 'OK', 'Ok', 'ok'];
    const scopes = [...document.querySelectorAll('.ant-popover,.ant-modal,.ant-modal-wrap')].filter(visible);
    for (const scope of scopes) {
      const buttons = [...scope.querySelectorAll('button,a,[role="button"]')].filter(visible);
      const button = buttons.find(el => labels.some(label => normalize(text(el)).includes(normalize(label))));
      if (button) {
        clickElement(button);
        await sleep(220);
        return true;
      }
    }
    return false;
  }
}
"""


def _log(level: str, message: str, **extra: Any) -> None:
    logger = BASE.get("_log")
    if callable(logger):
        logger(level, message, **extra)
        return
    print(f"[{level}] {message} {extra if extra else ''}")


def _request_stop_from_gui() -> None:
    STOP_EVENT.set()
    robots = _active_robots_snapshot()
    _log("WARN", "已请求停止当前任务，正在中断浏览器自动化连接", activeRobots=len(robots))
    for robot in robots:
        close = getattr(robot, "close", None)
        if not callable(close):
            continue
        try:
            close()
        except Exception as exc:
            _log("WARN", "停止任务时关闭机器人连接失败", error=_safe_error_text(exc))
    _cleanup_runtime_resources(kill_children=False)


def _acquire_single_instance_lock() -> bool:
    global INSTANCE_LOCK_HANDLE
    if INSTANCE_LOCK_HANDLE is not None:
        return True
    lock_path = PIPELINE_CONFIG_PATH.parent / "DxmTemuTerminalRobot.lock"
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+", encoding="utf-8")
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                handle.close()
                return False
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                return False
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        INSTANCE_LOCK_HANDLE = handle
        return True
    except Exception as exc:
        _log("WARN", "单实例锁创建失败，将继续启动", error=_safe_error_text(exc))
        return True


def _release_single_instance_lock() -> None:
    global INSTANCE_LOCK_HANDLE
    lock_path = PIPELINE_CONFIG_PATH.parent / "DxmTemuTerminalRobot.lock"
    handle = INSTANCE_LOCK_HANDLE
    INSTANCE_LOCK_HANDLE = None
    if handle is not None:
        try:
            handle.close()
        except Exception:
            pass
    try:
        if lock_path.exists():
            lock_path.unlink()
    except Exception as exc:
        _log("WARN", "删除单实例锁文件失败", error=_safe_error_text(exc), path=str(lock_path))


def _show_already_running_message() -> None:
    message = "DxmTemuTerminalRobot 已经在运行，请先关闭现有窗口。"
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("DxmTemuTerminalRobot", message, parent=root)
        root.destroy()
    except Exception:
        print(message)


def _exit_process_soon(code: int = 0, delay: float = 0.2) -> None:
    def exit_now() -> None:
        _cleanup_on_process_exit()
        try:
            sys.stdout.flush()
        except Exception:
            pass
        try:
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(code)

    timer = threading.Timer(delay, exit_now)
    timer.daemon = True
    timer.start()


def _cleanup_product_attr_session_cache() -> None:
    try:
        PRODUCT_ATTR_SESSION_CACHE_PATH.unlink(missing_ok=True)
    except Exception as exc:
        _log("WARN", "产品属性会话缓存清理失败", error=_safe_error_text(exc), path=str(PRODUCT_ATTR_SESSION_CACHE_PATH))


def _cleanup_on_process_exit() -> None:
    global CLEANUP_DONE
    with CLEANUP_LOCK:
        if CLEANUP_DONE:
            return
        CLEANUP_DONE = True
        try:
            _cleanup_product_attr_session_cache()
        except Exception as exc:
            _log("WARN", "退出时清理产品属性会话缓存失败", error=_safe_error_text(exc))
        try:
            _cleanup_runtime_resources(kill_children=True)
        except Exception as exc:
            _log("WARN", "退出时清理运行资源失败", error=_safe_error_text(exc))
        try:
            _release_single_instance_lock()
        except Exception as exc:
            _log("WARN", "退出时释放单实例锁失败", error=_safe_error_text(exc))


def _close_main_window_and_exit(root: Any) -> None:
    global APP_EXITING
    if APP_EXITING:
        return
    APP_EXITING = True
    _log("WARN", "主窗口已关闭，正在退出机器人进程")
    try:
        _request_stop_from_gui()
    except Exception as exc:
        _log("WARN", "关闭主窗口时停止任务失败", error=_safe_error_text(exc))
    try:
        _cleanup_on_process_exit()
    except Exception as exc:
        _log("WARN", "关闭主窗口时清理进程失败", error=_safe_error_text(exc))
    try:
        root.quit()
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass
    _exit_process_soon(0, delay=0.15)


def _save_json(name: str, data: Any) -> Path | None:
    saver = BASE.get("_save_json")
    if callable(saver):
        return saver(name, data)
    return None


def _safe_error_text(value: Any) -> str:
    helper = BASE.get("_safe_error_text")
    if callable(helper):
        return helper(value)
    return str(value).encode("utf-8", errors="replace").decode("utf-8", errors="replace")


atexit.register(_cleanup_on_process_exit)


def _normalize_image_postprocess_config(value: Any) -> dict[str, Any]:
    config = dict(DEFAULT_IMAGE_POSTPROCESS)
    if isinstance(value, dict):
        config.update({key: value.get(key, config[key]) for key in config})
    config["enabled"] = bool(config.get("enabled", True))
    for key in ("targetWidth", "targetHeight", "quality", "maxBytes", "minSourceWidth", "minSourceHeight"):
        try:
            config[key] = int(config.get(key) or DEFAULT_IMAGE_POSTPROCESS[key])
        except Exception:
            config[key] = DEFAULT_IMAGE_POSTPROCESS[key]
    config["targetWidth"] = max(1, config["targetWidth"])
    config["targetHeight"] = max(1, config["targetHeight"])
    config["quality"] = min(95, max(50, config["quality"]))
    config["maxBytes"] = max(128 * 1024, config["maxBytes"])
    config["minSourceWidth"] = max(1, config["minSourceWidth"])
    config["minSourceHeight"] = max(1, config["minSourceHeight"])
    config["outputFormat"] = str(config.get("outputFormat") or "jpg").strip().lower()
    if config["outputFormat"] not in {"jpg", "jpeg", "png", "webp"}:
        config["outputFormat"] = "jpg"
    config["mode"] = str(config.get("mode") or "pad").strip().lower()
    if config["mode"] not in {"pad", "cover"}:
        config["mode"] = "pad"
    config["background"] = str(config.get("background") or "#FFFFFF").strip() or "#FFFFFF"
    config["compressorPath"] = str(config.get("compressorPath") or DEFAULT_IMAGE_POSTPROCESS["compressorPath"]).strip()
    return config


def _normalize_feishu_bot_config(value: Any) -> dict[str, Any]:
    config = dict(DEFAULT_FEISHU_BOT)
    if isinstance(value, dict):
        config.update({key: value.get(key, config[key]) for key in config})
    env_webhook = os.environ.get("DXM_FEISHU_WEBHOOK", "").strip()
    env_secret = os.environ.get("DXM_FEISHU_SECRET", "").strip()
    if env_webhook:
        config["webhookUrl"] = env_webhook
        config["enabled"] = True
    if env_secret:
        config["secret"] = env_secret
    for key in ("enabled", "notifyOnError", "notifyOnStop", "notifyOnSuccess"):
        config[key] = bool(config.get(key, DEFAULT_FEISHU_BOT[key]))
    for key in ("webhookUrl", "secret", "keyword"):
        config[key] = str(config.get(key) or "").strip()
    if not config["webhookUrl"]:
        config["enabled"] = False
    return config


def _split_warehouse_names(value: Any) -> list[str]:
    helper = BASE.get("_split_config_names")
    if callable(helper):
        try:
            return [str(item).strip() for item in helper(str(value or "")) if str(item).strip()]
        except Exception:
            pass
    text = str(value or "")
    for mark in ("，", "、", ";", "；", "|", "\n", "\r", "\t"):
        text = text.replace(mark, ",")
    return [item.strip() for item in text.split(",") if item.strip()]


def _warehouse_base_name(value: Any) -> str:
    text = " ".join(str(value or "").replace("\u00a0", " ").split()).strip()
    for suffix in ("（其他）", "(其他)", "（其它）", "(其它)"):
        if text.endswith(suffix):
            return text[: -len(suffix)].strip()
    return text


def _warehouse_dedupe_key(value: Any) -> str:
    text = _warehouse_base_name(value)
    for mark in (" ", "\u00a0", "-", "_", "，", ",", "、", "/", "（", "）", "(", ")"):
        text = text.replace(mark, "")
    return text.lower()


def _warehouse_candidate_priority(value: Any) -> tuple[int, int]:
    text = str(value or "")
    has_context = any(suffix in text for suffix in ("（其他）", "(其他)", "（其它）", "(其它)"))
    return (1 if has_context else 0, len(text))


def _dedupe_warehouse_names(values: Any) -> list[str]:
    raw = values if isinstance(values, list) else _split_warehouse_names(values)
    names: list[str] = []
    indexes: dict[str, int] = {}
    for value in raw:
        text = " ".join(str(value or "").replace("\u00a0", " ").split()).strip()
        if not text or text == "全部":
            continue
        key = _warehouse_dedupe_key(text)
        if not key:
            continue
        if key in indexes:
            existing_index = indexes[key]
            if _warehouse_candidate_priority(text) > _warehouse_candidate_priority(names[existing_index]):
                names[existing_index] = text
            continue
        indexes[key] = len(names)
        names.append(text)
    return names


def _normalize_warehouse_templates(value: Any) -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    source = value if isinstance(value, list) else []
    for index, item in enumerate(source, start=1):
        if isinstance(item, dict):
            names = _dedupe_warehouse_names(item.get("warehouseNames") or item.get("warehouseName") or "")
            name = str(item.get("name") or f"仓库模板 {index}").strip()
            shipping_template = str(item.get("shippingTemplate") or "").strip()
            shipping_lead_days = item.get("shippingLeadDays")
            updated_at = str(item.get("updatedAt") or "").strip()
        else:
            names = _dedupe_warehouse_names(str(item or ""))
            name = f"仓库模板 {index}"
            shipping_template = ""
            shipping_lead_days = None
            updated_at = ""
        if not names:
            continue
        try:
            lead_days = int(shipping_lead_days) if shipping_lead_days not in (None, "") else None
        except Exception:
            lead_days = None
        record: dict[str, Any] = {
            "name": name or f"仓库模板 {index}",
            "warehouseName": "，".join(names),
            "warehouseNames": names,
        }
        if shipping_template:
            record["shippingTemplate"] = shipping_template
        if lead_days is not None:
            record["shippingLeadDays"] = max(1, lead_days)
        if updated_at:
            record["updatedAt"] = updated_at
        templates.append(record)
    return templates[:30]


def _save_warehouse_template_selection(
    names: list[str],
    *,
    template_name: str = "默认仓库模板",
    source: str = "warehouse-self-check",
) -> dict[str, Any]:
    selected_names = _dedupe_warehouse_names(names)
    if not selected_names:
        raise RuntimeError("没有选择可保存的仓库")
    config = _load_pipeline_config()
    try:
        shipping_lead_days = int(config.get("shippingLeadDays") or BASE.get("DEFAULT_SHIPPING_LEAD_DAYS") or 9)
    except Exception:
        shipping_lead_days = int(BASE.get("DEFAULT_SHIPPING_LEAD_DAYS") or 9)
    config["warehouseName"] = "，".join(selected_names)
    templates = _normalize_warehouse_templates(config.get("warehouseTemplates"))
    record = {
        "name": template_name.strip() or "默认仓库模板",
        "warehouseName": config["warehouseName"],
        "warehouseNames": selected_names,
        "shippingTemplate": str(config.get("shippingTemplate") or "").strip(),
        "shippingLeadDays": shipping_lead_days,
        "source": source,
        "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    replaced = False
    for index, item in enumerate(templates):
        if str(item.get("name") or "").strip() == record["name"]:
            templates[index] = record
            replaced = True
            break
    if not replaced:
        templates.insert(0, record)
    config["warehouseTemplates"] = templates[:30]
    _save_pipeline_config(config)
    _log("OK", "仓库模板已保存", name=record["name"], warehouses=record["warehouseName"])
    return config


def _format_warehouse_names(names: list[str]) -> str:
    return "，".join(_dedupe_warehouse_names(names))


def _iter_tk_widgets(widget: Any) -> list[Any]:
    widgets: list[Any] = []
    stack = [widget]
    while stack:
        node = stack.pop()
        widgets.append(node)
        try:
            children = list(node.winfo_children())
        except Exception:
            children = []
        stack.extend(reversed(children))
    return widgets


def _widget_text(widget: Any) -> str:
    try:
        return str(widget.cget("text") or "").strip()
    except Exception:
        return ""


def _entry_text(widget: Any) -> str:
    try:
        return str(widget.get() or "").strip()
    except Exception:
        return ""


def _set_entry_text(widget: Any, value: str) -> bool:
    try:
        widget.configure(state="normal")
    except Exception:
        pass
    try:
        widget.delete(0, "end")
        widget.insert(0, value)
        return True
    except Exception:
        return False


def _is_warehouse_label(text: str) -> bool:
    normalized = text.replace("：", ":").strip()
    return normalized in {"仓库", "仓库:", "选择仓库", "选择仓库:"} or normalized.startswith("选择仓库")


def _find_warehouse_entries(root: Any) -> list[Any]:
    widgets = _iter_tk_widgets(root)
    labels = [node for node in widgets if _is_warehouse_label(_widget_text(node))]
    entries = [
        node
        for node in widgets
        if str(getattr(node, "winfo_class", lambda: "")()).lower() in {"entry", "tentry"}
    ]
    matches: list[Any] = []
    for label in labels:
        try:
            lx = label.winfo_rootx()
            ly = label.winfo_rooty() + label.winfo_height() / 2
        except Exception:
            continue
        candidates: list[tuple[float, float, Any]] = []
        for entry in entries:
            try:
                ex = entry.winfo_rootx()
                ey = entry.winfo_rooty() + entry.winfo_height() / 2
                if ex < lx:
                    continue
                dy = abs(ey - ly)
                if dy > 32:
                    continue
                candidates.append((dy, ex - lx, entry))
            except Exception:
                continue
        if candidates:
            candidates.sort(key=lambda item: (item[0], item[1]))
            match = candidates[0][2]
            if match not in matches:
                matches.append(match)
    return matches


def _backfill_warehouse_textboxes(names: list[str]) -> int:
    warehouse_text = _format_warehouse_names(names)
    if not warehouse_text:
        return 0
    count = 0
    for root in _active_control_roots_snapshot():
        try:
            root.update_idletasks()
        except Exception:
            pass
        for entry in _find_warehouse_entries(root):
            before = _entry_text(entry)
            if _set_entry_text(entry, warehouse_text):
                count += 1
                _log("INFO", "已回填主窗口仓库文本框", before=before, after=warehouse_text)
    return count


def _apply_warehouse_selection_to_runtime(names: list[str]) -> dict[str, Any]:
    selected_names = _dedupe_warehouse_names(names)
    if not selected_names:
        raise RuntimeError("没有可回填的仓库")
    warehouse_text = _format_warehouse_names(selected_names)
    config = _load_pipeline_config()
    config["warehouseName"] = warehouse_text
    _save_pipeline_config(config)
    updated_widgets = _backfill_warehouse_textboxes(selected_names)
    _log("OK", "仓库自检结果已回填", warehouses=warehouse_text, updatedTextboxes=updated_widgets)
    return config


_base_load_pipeline_config = BASE.get("_load_pipeline_config")
_base_save_pipeline_config = BASE.get("_save_pipeline_config")


def _load_pipeline_config() -> dict[str, Any]:
    if callable(_base_load_pipeline_config):
        config = _base_load_pipeline_config()
    else:
        config = {}
    if not isinstance(config, dict):
        config = {}
    try:
        if PIPELINE_CONFIG_PATH.exists():
            raw_config = json.loads(PIPELINE_CONFIG_PATH.read_text(encoding="utf-8-sig"))
            if isinstance(raw_config, dict):
                config.update(raw_config)
    except Exception as exc:
        _log("WARN", "读取扩展流程配置失败", error=_safe_error_text(exc))
    config["imagePostprocess"] = _normalize_image_postprocess_config(config.get("imagePostprocess"))
    config["feishuBot"] = _normalize_feishu_bot_config(config.get("feishuBot"))
    config["warehouseTemplates"] = _normalize_warehouse_templates(config.get("warehouseTemplates"))
    return config


def _save_pipeline_config(config: dict[str, Any]) -> None:
    existing_image_config: dict[str, Any] | None = None
    existing_feishu_config: dict[str, Any] | None = None
    existing_warehouse_templates: list[Any] | None = None
    try:
        if PIPELINE_CONFIG_PATH.exists():
            existing = json.loads(PIPELINE_CONFIG_PATH.read_text(encoding="utf-8-sig"))
            if isinstance(existing, dict) and isinstance(existing.get("imagePostprocess"), dict):
                existing_image_config = existing["imagePostprocess"]
            if isinstance(existing, dict) and isinstance(existing.get("feishuBot"), dict):
                existing_feishu_config = existing["feishuBot"]
            if isinstance(existing, dict) and isinstance(existing.get("warehouseTemplates"), list):
                existing_warehouse_templates = existing["warehouseTemplates"]
    except Exception:
        existing_image_config = None
        existing_feishu_config = None
        existing_warehouse_templates = None

    image_config = _normalize_image_postprocess_config(
        config.get("imagePostprocess") if isinstance(config, dict) and "imagePostprocess" in config else existing_image_config
    )
    feishu_config = _normalize_feishu_bot_config(
        config.get("feishuBot") if isinstance(config, dict) and "feishuBot" in config else existing_feishu_config
    )
    warehouse_templates = _normalize_warehouse_templates(
        config.get("warehouseTemplates") if isinstance(config, dict) and "warehouseTemplates" in config else existing_warehouse_templates
    )
    if callable(_base_save_pipeline_config):
        _base_save_pipeline_config(config)
    try:
        PIPELINE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {}
        if PIPELINE_CONFIG_PATH.exists():
            loaded = json.loads(PIPELINE_CONFIG_PATH.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                payload.update(loaded)
        if isinstance(config, dict):
            payload.update(config)
        payload["imagePostprocess"] = image_config
        payload["feishuBot"] = feishu_config
        payload["warehouseTemplates"] = warehouse_templates
        PIPELINE_CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        _log("WARN", "图片后处理配置保存失败", error=_safe_error_text(exc))


BASE["_load_pipeline_config"] = _load_pipeline_config
BASE["_save_pipeline_config"] = _save_pipeline_config


def _feishu_sign(secret: str, timestamp: int) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _send_feishu_text(title: str, body: str, *, level: str = "ERROR", config: dict[str, Any] | None = None) -> bool:
    cfg = _normalize_feishu_bot_config((config or _load_pipeline_config()).get("feishuBot") if isinstance(config or {}, dict) else None)
    if not cfg.get("enabled") or not cfg.get("webhookUrl"):
        return False

    keyword = str(cfg.get("keyword") or "").strip()
    prefix = f"【{keyword}】" if keyword else "【店小秘】"
    text = f"{prefix}{title}\n级别：{level}\n时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n{body}".strip()
    payload: dict[str, Any] = {
        "msg_type": "text",
        "content": {"text": text},
    }
    secret = str(cfg.get("secret") or "").strip()
    if secret:
        timestamp = int(time.time())
        payload["timestamp"] = str(timestamp)
        payload["sign"] = _feishu_sign(secret, timestamp)

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        str(cfg["webhookUrl"]),
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read().decode("utf-8", errors="replace")
        try:
            result = json.loads(raw)
        except Exception:
            result = {"raw": raw}
        code = result.get("code", result.get("StatusCode", 0)) if isinstance(result, dict) else 0
        if code not in (0, "0", None):
            _log("WARN", "飞书机器人通知返回非成功状态", response=result)
            return False
        _log("OK", "飞书机器人通知已发送", title=title)
        return True
    except Exception as exc:
        _log("WARN", "飞书机器人通知发送失败", error=_safe_error_text(exc))
        return False


def _page_error_summary_for_webhook(robot: Any | None) -> str:
    page = getattr(robot, "page", None) if robot is not None else None
    if page is None:
        return ""
    parts: list[str] = []
    try:
        url = str(getattr(page, "url", "") or "").strip()
    except Exception:
        url = ""
    if url:
        parts.append(f"页面：{url}")

    errors: list[str] = []
    try:
        frontend_errors = _frontend_required_errors(page)
    except Exception as exc:
        frontend_errors = []
        _log("WARN", "飞书错误通知读取前台必填错误失败", error=_safe_error_text(exc))
    for item in frontend_errors:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        text = str(item.get("text") or "").strip()
        item_text = str(item.get("itemText") or "").strip()
        if label and text:
            errors.append(f"{label}: {text}")
        elif text:
            errors.append(text)
        elif item_text:
            errors.append(item_text)

    try:
        visible_messages = page.evaluate(
            r"""
() => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function visible(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'&&r.bottom>=0&&r.right>=0&&r.top<=innerHeight&&r.left<=innerWidth;
  }
  const selectors=[
    '.ant-message-notice-content',
    '.ant-notification-notice-message',
    '.ant-notification-notice-description',
    '.ant-form-item-explain-error',
    '[class*="error"]'
  ];
  const pattern=/(请输入|请选择|必填|不能为空|required|失败|错误|异常|超时|不合法|不能|未检测|未找到|fail|error|invalid)/i;
  const out=[];
  const seen=new Set();
  for(const node of document.querySelectorAll(selectors.join(','))){
    if(!visible(node)) continue;
    const text=clean(node.innerText||node.textContent);
    if(!text || text.length>260 || !pattern.test(text)) continue;
    const key=text.toLowerCase();
    if(seen.has(key)) continue;
    seen.add(key);
    out.push(text);
    if(out.length>=12) break;
  }
  return out;
}
"""
        )
    except Exception as exc:
        visible_messages = []
        _log("WARN", "飞书错误通知读取页面可见错误失败", error=_safe_error_text(exc))
    if isinstance(visible_messages, list):
        for item in visible_messages:
            text = str(item or "").strip()
            if text:
                errors.append(text)

    unique: list[str] = []
    seen: set[str] = set()
    for item in errors:
        text = " ".join(str(item).split())
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
        if len(unique) >= 10:
            break
    if unique:
        parts.append("页面报错：")
        parts.extend(f"- {item}" for item in unique)
    return "\n".join(parts).strip()


def _notify_task_error(task: str, error: Any, *, config: dict[str, Any] | None = None, robot: Any | None = None) -> None:
    cfg = _normalize_feishu_bot_config((config or _load_pipeline_config()).get("feishuBot") if isinstance(config or {}, dict) else None)
    if not cfg.get("notifyOnError", True):
        return
    body = f"任务：{task}\n错误：{_safe_error_text(error)}"
    page_summary = _page_error_summary_for_webhook(robot)
    if page_summary:
        body = f"{body}\n\n{page_summary}"
    _send_feishu_text(
        "自动流程报错",
        body,
        level="ERROR",
        config={"feishuBot": cfg},
    )


def _notify_task_stopped(task: str, *, config: dict[str, Any] | None = None) -> None:
    cfg = _normalize_feishu_bot_config((config or _load_pipeline_config()).get("feishuBot") if isinstance(config or {}, dict) else None)
    if not cfg.get("notifyOnStop", True):
        return
    _send_feishu_text(
        "自动流程已停止",
        f"任务：{task}\n原因：用户点击停止或流程收到停止请求。",
        level="WARN",
        config={"feishuBot": cfg},
    )


def _notify_task_success(task: str, *, config: dict[str, Any] | None = None) -> None:
    cfg = _normalize_feishu_bot_config((config or _load_pipeline_config()).get("feishuBot") if isinstance(config or {}, dict) else None)
    if not cfg.get("notifyOnSuccess", False):
        return
    _send_feishu_text(
        "自动流程完成",
        f"任务：{task}",
        level="OK",
        config={"feishuBot": cfg},
    )


def _collect_required_info_errors(value: Any, path: str = "") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        validation = value.get("validation")
        if isinstance(validation, dict):
            missing = validation.get("missingRequired") or validation.get("missing") or validation.get("missingFields")
            if _is_basic_info_validation_path(path):
                missing = _filter_optional_basic_attr_missing_values(missing)
            if missing:
                errors.append(f"{path or 'validation'} missingRequired={missing}")
            if validation.get("ok") is False and not missing:
                errors.append(f"{path or 'validation'} ok=False")
        for key in ("missingRequired", "missingFields", "unfilledRequired", "requiredMissing"):
            missing_value = value.get(key)
            if _is_basic_info_validation_path(path):
                missing_value = _filter_optional_basic_attr_missing_values(missing_value)
            if missing_value:
                errors.append(f"{path + '.' if path else ''}{key}={missing_value}")
        if value.get("ok") is False and any(token in path for token in ("基本信息", "产品信息", "变种信息", "运输信息")):
            errors.append(f"{path or 'result'} ok=False")
        for key in ("before", "after", "result", "data"):
            if isinstance(value.get(key), dict):
                errors.extend(_collect_required_info_errors(value[key], f"{path}.{key}" if path else key))
    return errors


def _validate_required_info_result(step_name: str, value: Any) -> None:
    if not any(token in step_name for token in ("基本信息", "产品信息", "变种信息", "运输信息")):
        return
    errors = _collect_required_info_errors(value, step_name)
    if errors:
        raise RuntimeError("信息未填全：" + " | ".join(errors[:8]))


def _basic_input_attr_default_value(label: str, product_info: dict[str, Any] | None = None) -> str:
    clean_label = str(label or "").replace(" ", "")
    if "平方克重" in clean_label:
        return "200"
    return ""


def _basic_input_attr_default_unit(label: str, product_info: dict[str, Any] | None = None) -> str:
    clean_label = str(label or "").replace(" ", "")
    if "平方克重" in clean_label:
        return "g/㎡"
    return ""


def _basic_input_attr_rule_value(label: str, product_info: dict[str, Any] | None = None) -> str:
    lookup = BASE.get("_lookup_batch_attribute_rule")
    batch_value = ""
    if callable(lookup):
        try:
            batch_value = str(lookup(label, _load_pipeline_config()) or "").strip()
        except Exception as exc:
            _log("WARN", "产品属性文本框批次规则读取失败", field=label, error=_safe_error_text(exc))
    return batch_value or _basic_input_attr_default_value(label, product_info)


def _basic_input_attr_rule_unit(label: str, product_info: dict[str, Any] | None = None) -> str:
    return _basic_input_attr_default_unit(label, product_info)


def _basic_attr_label_key(label: str) -> str:
    return "".join(str(label or "").replace("＊", "*").replace("*", "").replace("：", ":").replace(":", "").split())


def _is_optional_basic_attr_label(label: str) -> bool:
    key = _basic_attr_label_key(label)
    return any(token in key for token in ("适用年龄段", "节日", "品牌名", "品牌"))


def _missing_required_label_text(value: Any) -> str:
    text = " ".join(str(value or "").replace("[", " ").replace("]", " ").replace("'", " ").replace('"', " ").split()).strip()
    for sep in (":", "："):
        if sep in text:
            head = text.split(sep, 1)[0].strip()
            if head:
                return head
    return text


def _filter_optional_basic_attr_missing_values(value: Any) -> Any:
    if isinstance(value, (list, tuple, set)):
        kept = [item for item in value if not _is_optional_basic_attr_label(_missing_required_label_text(item))]
        return kept
    if _is_optional_basic_attr_label(_missing_required_label_text(value)):
        return []
    return value


def _is_basic_info_validation_path(path: str) -> bool:
    text = str(path or "")
    return ("基本信息" in text) or ("basic" in text.lower())


def _text_mentions_label(text: str, label: str) -> bool:
    key = _basic_attr_label_key(label)
    haystack = _basic_attr_label_key(text)
    return bool(key and haystack and (key in haystack or haystack in key))


def _frontend_error_text_for_basic_attr(page: Any) -> str:
    try:
        errors = _frontend_required_errors(page, product_attrs_only=True)
    except Exception:
        return ""
    parts: list[str] = []
    for item in errors:
        if not isinstance(item, dict):
            continue
        parts.append(str(item.get("label") or ""))
        parts.append(str(item.get("text") or ""))
        parts.append(str(item.get("itemText") or ""))
    return " | ".join(part for part in parts if part)


def _basic_select_attr_rule_candidates(label: str, product_info: dict[str, Any] | None = None) -> list[str]:
    key = _basic_attr_label_key(label)
    candidates: list[str] = []
    lookup = BASE.get("_lookup_batch_attribute_rule")
    if callable(lookup):
        try:
            batch_value = str(lookup(label, _load_pipeline_config()) or "").strip()
            if batch_value:
                candidates.append(batch_value)
        except Exception as exc:
            _log("WARN", "产品属性下拉批次规则读取失败", field=label, error=_safe_error_text(exc))
    defaults: list[str] = []
    if "类型" in key:
        defaults = ["详见商品详情"]
    elif "颜色" in key:
        defaults = ["灰色", "黑色", "白色"]
    elif "数量" in key:
        defaults = ["1"]
    elif "材料组成" in key:
        defaults = ["纺织材料"]
    elif "织造方式" in key:
        defaults = ["针织(含钩织、毛织面料)", "无纺布"]
    elif "成分" in key:
        defaults = ["聚酯纤维(涤纶)", "聚酯纤维（涤纶）", "聚酯纤维", "涤纶"]
    elif "护理说明" in key:
        defaults = ["手洗或干洗"]
    for value in defaults:
        if value and value not in candidates:
            candidates.append(value)
    return candidates


def _basic_choice_key(value: str) -> str:
    return "".join(
        ch
        for ch in str(value or "").lower()
        if ch not in " \t\r\n　:：,，、()（）[]【】-_/\\"
    )


def _basic_choice_matches(value: str, candidates: list[str]) -> bool:
    value_key = _basic_choice_key(value)
    if not value_key:
        return False
    for candidate in candidates:
        candidate_key = _basic_choice_key(candidate)
        if candidate_key and (value_key == candidate_key or value_key in candidate_key or candidate_key in value_key):
            return True
    return False


def _read_basic_attr_value(page: Any, label: str) -> str:
    value_reader = BASE.get("GET_BASIC_ATTR_VALUE_BY_LABEL_JS")
    if not isinstance(value_reader, str) or not value_reader.strip():
        return ""
    try:
        state = page.evaluate(value_reader, label)
    except Exception:
        return ""
    if isinstance(state, dict):
        return str(state.get("value") or "").strip()
    return ""


def _basic_attr_value_is_meaningful(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    key = _basic_choice_key(text)
    if not key:
        return False
    placeholders = (
        "\u8bf7\u9009\u62e9",
        "\u8bf7\u9009\u62e9\u4ea7\u54c1\u5c5e\u6027",
        "\u8f93\u5165\u641c\u7d22\u503c",
        "select",
        "please select",
    )
    for placeholder in placeholders:
        placeholder_key = _basic_choice_key(placeholder)
        if placeholder_key and (key == placeholder_key or key in placeholder_key):
            return False
    return True


def _resync_basic_attr_control(page: Any, label: str) -> dict[str, Any]:
    if page is None or not str(label or "").strip():
        return {"ok": False, "error": "missing_page_or_label"}
    try:
        result = page.evaluate(BASIC_ATTR_SYNC_CONTROL_BY_LABEL_JS, label)
    except Exception as exc:
        return {"ok": False, "error": _safe_error_text(exc)}
    return result if isinstance(result, dict) else {"ok": bool(result), "result": result}


def _frontend_required_error_is_resolved_by_basic_attr_value(
    page: Any,
    *,
    label: str,
    text: str,
    item_text: str = "",
) -> bool:
    if page is None or not str(label or "").strip():
        return False
    error_text = f"{text or ''} {item_text or ''}"
    if not any(token in error_text for token in ("\u8bf7\u9009\u62e9", "\u8bf7\u8f93\u5165", "\u5fc5\u586b", "required")):
        return False
    _resync_basic_attr_control(page, label)
    time.sleep(0.08)
    current_value = _read_basic_attr_value(page, label)
    if not _basic_attr_value_is_meaningful(current_value):
        return False
    _log(
        "INFO",
        "产品属性前台旧错误已忽略：字段已有有效值",
        field=label,
        value=current_value,
        error=text,
    )
    return True


def _extract_product_category_path(value: Any) -> str:
    text = " ".join(str(value or "").replace("\uff1e", ">").split()).strip()
    if not text:
        return ""
    if "\u9009\u62e9\u5206\u7c7b" in text:
        text = text.split("\u9009\u62e9\u5206\u7c7b", 1)[1]
    elif "\u4ea7\u54c1\u5206\u7c7b" in text:
        text = text.split("\u4ea7\u54c1\u5206\u7c7b", 1)[1]
    for stop in (
        "\u4ea7\u54c1\u5c5e\u6027",
        "\u5e97\u5c0f\u79d8\u4fe1\u606f",
        "\u6765\u6e90URL",
        "\u5e73\u65b9\u514b\u91cd",
        "\u6750\u6599\u7ec4\u6210",
        "\u6210\u5206",
        "\u98ce\u683c",
        "\u56fe\u6848",
        "\u6750\u6599",
        "\u5f62\u72b6",
        "\u54c1\u724c\u540d",
        "\u62a4\u7406\u8bf4\u660e",
    ):
        if stop in text:
            text = text.split(stop, 1)[0]
    text = re.sub(r"\s*>\s*", " > ", text).strip(" >")
    parts = [part.strip() for part in text.split(">") if part.strip()]
    if len(parts) >= 2:
        cleaned: list[str] = []
        for part in parts[:8]:
            part = re.sub(r"^(?:\*|＊|\s)+", "", part).strip()
            if part:
                cleaned.append(part)
        if len(cleaned) >= 2:
            return " > ".join(cleaned)
    return ""


def _product_attr_session_category_text(scan: dict[str, Any] | None, context: dict[str, Any] | None = None) -> str:
    product_info = scan.get("productInfo") if isinstance(scan, dict) and isinstance(scan.get("productInfo"), dict) else {}
    candidates = [
        product_info.get("category"),
        product_info.get("categoryPath"),
        (context or {}).get("category") if isinstance(context, dict) else "",
    ]
    for item in candidates:
        text = " ".join(str(item or "").split()).strip()
        category_path = _extract_product_category_path(text)
        if category_path:
            return category_path[:240]
        if text and len(text) <= 80 and "\u4ea7\u54c1\u5c5e\u6027" not in text:
            return text[:80]
    return ""


def _product_attr_session_category_key(scan: dict[str, Any] | None, context: dict[str, Any] | None = None) -> str:
    text = _product_attr_session_category_text(scan, context)
    return _basic_choice_key(text)


def _write_product_attr_session_cache() -> None:
    with PRODUCT_ATTR_SESSION_CACHE_LOCK:
        try:
            PRODUCT_ATTR_SESSION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            PRODUCT_ATTR_SESSION_CACHE["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
            PRODUCT_ATTR_SESSION_CACHE_PATH.write_text(
                json.dumps(PRODUCT_ATTR_SESSION_CACHE, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            _log("WARN", "产品属性会话缓存写入失败", error=_safe_error_text(exc), path=str(PRODUCT_ATTR_SESSION_CACHE_PATH))


def _find_product_attr_session_cache_entry(category_cache: dict[str, Any], label: str, component: str) -> dict[str, Any] | None:
    fields = category_cache.get("fields") if isinstance(category_cache, dict) else None
    if not isinstance(fields, dict):
        return None
    label_key = _basic_attr_label_key(label)
    for entry in fields.values():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("component") or "") != component:
            continue
        entry_label = str(entry.get("label") or "")
        if entry_label == label or _basic_attr_label_key(entry_label) == label_key:
            return entry
    return None


def _record_product_attr_session_cache(scan: dict[str, Any] | None, applied: list[dict[str, Any]], *, source: str) -> None:
    category_key = _product_attr_session_category_key(scan)
    category_text = _product_attr_session_category_text(scan)
    if not category_key or not applied:
        return
    changed = False
    with PRODUCT_ATTR_SESSION_CACHE_LOCK:
        categories = PRODUCT_ATTR_SESSION_CACHE.setdefault("categories", {})
        if not isinstance(categories, dict):
            PRODUCT_ATTR_SESSION_CACHE["categories"] = {}
            categories = PRODUCT_ATTR_SESSION_CACHE["categories"]
        category_cache = categories.setdefault(
            category_key,
            {"category": category_text, "fields": {}, "createdAt": time.strftime("%Y-%m-%d %H:%M:%S")},
        )
        if category_text:
            category_cache["category"] = category_text
        fields = category_cache.setdefault("fields", {})
        for item in applied:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            component = str(item.get("component") or "").strip()
            value = str(item.get("value") or "").strip()
            if not label or component not in {"input", "ant-select", "checkbox-group"} or not _basic_attr_value_is_meaningful(value):
                continue
            contains_redline = BASE.get("_contains_redline")
            if callable(contains_redline) and contains_redline(value):
                continue
            key = _basic_attr_label_key(label) or label
            prior = fields.get(key) if isinstance(fields.get(key), dict) else {}
            fields[key] = {
                "label": label,
                "labelKey": key,
                "component": component,
                "value": value,
                "source": source,
                "count": int(prior.get("count") or 0) + 1 if isinstance(prior, dict) else 1,
                "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            changed = True
        if changed:
            category_cache["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if changed:
        _write_product_attr_session_cache()
        _log("INFO", "产品属性会话缓存已更新", category=category_text, fields=len(applied), path=str(PRODUCT_ATTR_SESSION_CACHE_PATH))


def _record_product_attr_session_cache_from_scan(scan: dict[str, Any] | None, *, source: str) -> None:
    if not isinstance(scan, dict) or not scan.get("ok"):
        return
    applied: list[dict[str, Any]] = []
    for attr in scan.get("attrs") or []:
        if not isinstance(attr, dict):
            continue
        if not attr.get("required") or attr.get("visible") is False:
            continue
        label = str(attr.get("label") or "").strip()
        component = str(attr.get("component") or "").strip()
        value = str(attr.get("value") or "").strip()
        if not label or component not in {"input", "ant-select", "checkbox-group"}:
            continue
        if _is_optional_basic_attr_label(label) or not _basic_attr_value_is_meaningful(value):
            continue
        applied.append({"label": label, "component": component, "value": value})
    _record_product_attr_session_cache(scan, applied, source=source)


def _apply_product_attr_session_cache(
    page: Any,
    scan: dict[str, Any] | None,
    choice_fields: list[dict[str, Any]],
    input_fields: list[dict[str, Any]],
) -> dict[str, Any]:
    category_key = _product_attr_session_category_key(scan)
    category_text = _product_attr_session_category_text(scan)
    if not category_key:
        return {"applied": [], "skipped": [], "reason": "missing_category"}
    with PRODUCT_ATTR_SESSION_CACHE_LOCK:
        categories = PRODUCT_ATTR_SESSION_CACHE.get("categories")
        category_cache = categories.get(category_key) if isinstance(categories, dict) else None
        if not isinstance(category_cache, dict):
            return {"applied": [], "skipped": [], "reason": "cache_miss"}

    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    remaining_choice = list(choice_fields)
    remaining_input = list(input_fields)

    def apply_field(field: dict[str, Any]) -> bool:
        label = str(field.get("label") or "").strip()
        component = str(field.get("component") or "").strip()
        entry = _find_product_attr_session_cache_entry(category_cache, label, component)
        if not entry:
            return False
        cached_value = str(entry.get("value") or "").strip()
        if not _basic_attr_value_is_meaningful(cached_value):
            return False
        contains_redline = BASE.get("_contains_redline")
        if callable(contains_redline) and contains_redline(cached_value):
            return False
        if component == "input":
            result = page.evaluate(BASIC_ATTR_SET_INPUT_BY_LABEL_JS, {"label": label, "value": cached_value, "unit": ""})
            current_value = _read_basic_attr_value(page, label)
            if isinstance(result, dict) and result.get("ok") and _basic_attr_value_is_meaningful(current_value or cached_value):
                applied.append({"label": label, "value": current_value or cached_value, "component": component, "source": "session_cache", "result": result})
                return True
            skipped.append({"label": label, "value": cached_value, "component": component, "reason": result, "source": "session_cache"})
            return False
        options = [str(item) for item in field.get("options") or []]
        chosen = _matching_basic_option(cached_value, options)
        if not chosen:
            skipped.append({"label": label, "value": cached_value, "component": component, "reason": "cached_value_not_in_current_options", "source": "session_cache"})
            return False
        if component == "checkbox-group":
            clicked = page.evaluate(STRICT_CLICK_BASIC_ATTR_CHECKBOX_BY_LABEL_JS, {"label": label, "value": chosen})
            result: dict[str, Any] = {"ok": bool(clicked), "method": "session-cache-checkbox", "value": chosen}
        else:
            result = _fill_basic_product_attr_select_by_mouse(page, label, [chosen], force=True)
        if isinstance(result, dict) and result.get("ok"):
            applied.append({"label": label, "value": chosen, "component": component, "source": "session_cache", "result": result})
            return True
        skipped.append({"label": label, "value": chosen, "component": component, "reason": result, "source": "session_cache"})
        return False

    for field in remaining_input:
        if apply_field(field):
            input_fields.remove(field)
    for field in remaining_choice:
        if apply_field(field):
            choice_fields.remove(field)
    if applied:
        _log("OK", "产品属性会话缓存已复用", category=category_text, fields="|".join(item["label"] for item in applied))
    return {"applied": applied, "skipped": skipped}


def _fill_basic_product_attrs_from_session_cache(page: Any, scan: dict[str, Any] | None = None) -> dict[str, Any]:
    scan_js = (BASE.get("LEGACY") or {}).get("BASIC_ATTR_SCAN_JS") if isinstance(BASE.get("LEGACY"), dict) else None
    if scan is None:
        if not isinstance(scan_js, str) or not scan_js.strip():
            return {"ok": True, "applied": [], "skipped": [], "reason": "missing_scan_js"}
        scan = page.evaluate(scan_js)
    if not isinstance(scan, dict) or not scan.get("ok"):
        return {"ok": False, "applied": [], "skipped": [], "reason": scan}

    attr_has_value = BASE.get("_attr_has_value")
    choice_fields: list[dict[str, Any]] = []
    input_fields: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    frontend_error_text = _frontend_error_text_for_basic_attr(page)

    for attr in scan.get("attrs") or []:
        if not isinstance(attr, dict):
            continue
        label = str(attr.get("label") or "").strip()
        component = str(attr.get("component") or "").strip()
        if not label or attr.get("visible") is False or not attr.get("required"):
            continue
        if _is_optional_basic_attr_label(label) or component not in {"input", "ant-select", "checkbox-group"}:
            continue
        current_value = str(attr.get("value") or "").strip()
        has_value = bool(attr_has_value(attr)) if callable(attr_has_value) else _basic_attr_value_is_meaningful(current_value)
        force = _text_mentions_label(frontend_error_text, label)
        if has_value and not force:
            continue
        if component == "input":
            input_fields.append({"label": label, "component": component})
            continue
        options = _collect_basic_attr_options_for_ai(page, label, component)
        if options:
            choice_fields.append({"label": label, "component": component, "options": options[:80]})
        else:
            skipped.append({"label": label, "component": component, "reason": "no_options_for_session_cache"})

    if not choice_fields and not input_fields:
        return {"ok": True, "applied": [], "skipped": skipped, "reason": "no_pending_fields"}

    category = _product_attr_session_category_text(scan)
    result = _apply_product_attr_session_cache(page, scan, choice_fields, input_fields)
    applied = result.get("applied") if isinstance(result, dict) else []
    result_skipped = result.get("skipped") if isinstance(result, dict) else []
    payload = {
        "ok": True,
        "category": category,
        "applied": applied if isinstance(applied, list) else [],
        "skipped": [*skipped, *(result_skipped if isinstance(result_skipped, list) else [])],
        "remainingChoice": [field.get("label") for field in choice_fields],
        "remainingInput": [field.get("label") for field in input_fields],
    }
    if payload["applied"]:
        _save_json("basic-product-attr-session-cache-fill", payload)
    elif category:
        _log("INFO", "产品属性会话缓存未命中或无可复用字段", category=category, fields="|".join([*(payload["remainingChoice"] or []), *(payload["remainingInput"] or [])]))
    return payload


def _safe_basic_attr_options(options: list[str]) -> list[str]:
    cleaner = BASE.get("_clean_attr_value")
    filter_safe = BASE.get("_filter_safe_options")
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in options:
        text = str(cleaner(item) if callable(cleaner) else item or "").strip()
        if not text or text in {"请选择", "全部", "输入搜索值"}:
            continue
        key = _basic_choice_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    if callable(filter_safe):
        try:
            return [str(item).strip() for item in filter_safe(cleaned) if str(item).strip()]
        except Exception as exc:
            _log("WARN", "AI 产品属性候选过滤失败，改用本地红线过滤", error=_safe_error_text(exc))
    contains_redline = BASE.get("_contains_redline")
    if callable(contains_redline):
        return [item for item in cleaned if not contains_redline(item)]
    return cleaned


def _collect_basic_select_options_by_wheel(page: Any, label: str, *, max_steps: int = 36) -> list[str]:
    box_js = BASE.get("GET_BASIC_ATTR_SELECT_BOX_BY_LABEL_JS")
    if not isinstance(box_js, str) or not box_js.strip():
        box_js = STRICT_GET_BASIC_ATTR_SELECT_BOX_BY_LABEL_JS
    try:
        box = page.evaluate(box_js, label)
    except Exception as exc:
        _log("WARN", "AI 产品属性下拉候选定位失败", field=label, error=_safe_error_text(exc))
        return []
    if not isinstance(box, dict) or not box.get("ok"):
        return []
    x = float(box.get("x") or 0) + float(box.get("w") or 0) / 2
    y = float(box.get("y") or 0) + float(box.get("h") or 0) / 2
    options: list[str] = []
    last_signature = ""
    stagnant_rounds = 0
    try:
        _close_active_dropdowns_for_basic_attrs(page)
        time.sleep(0.08)
        page.mouse.click(x, y)
        time.sleep(0.25)
    except Exception as exc:
        _log("WARN", "AI 产品属性下拉候选打开失败", field=label, error=_safe_error_text(exc))
        return []
    for _step in range(max_steps):
        try:
            state = page.evaluate(BASIC_ATTR_VISIBLE_DROPDOWN_OPTION_POINTS_JS, {"box": box, "candidates": []})
        except Exception as exc:
            _log("WARN", "AI 产品属性下拉候选读取失败", field=label, error=_safe_error_text(exc))
            break
        if not isinstance(state, dict):
            break
        for item in state.get("seen") or []:
            text = str(item or "").strip()
            if text and text not in options:
                options.append(text)
        signature = "|".join(str(item) for item in state.get("seen") or [])
        if signature == last_signature:
            stagnant_rounds += 1
        else:
            stagnant_rounds = 0
            last_signature = signature
        if state.get("atEnd") and stagnant_rounds >= 1:
            break
        dropdown_box = state.get("dropdownBox")
        if not isinstance(dropdown_box, dict):
            break
        try:
            sx = float(dropdown_box.get("x") or 0) + float(dropdown_box.get("w") or 0) / 2
            sy = float(dropdown_box.get("y") or 0) + min(float(dropdown_box.get("h") or 0) - 12, 160)
            page.mouse.move(sx, sy)
            page.mouse.wheel(0, 420)
            time.sleep(0.12)
        except Exception:
            break
    _close_active_dropdowns_for_basic_attrs(page)
    return _safe_basic_attr_options(options)


def _collect_basic_checkbox_options(page: Any, label: str) -> list[str]:
    reader = BASE.get("GET_BASIC_ATTR_CHECKBOX_OPTIONS_JS")
    if not isinstance(reader, str) or not reader.strip():
        reader = STRICT_GET_BASIC_ATTR_CHECKBOX_OPTIONS_JS
    try:
        data = page.evaluate(reader, label)
    except Exception as exc:
        _log("WARN", "AI 产品属性复选候选读取失败", field=label, error=_safe_error_text(exc))
        return []
    if isinstance(data, dict):
        return _safe_basic_attr_options([str(item) for item in data.get("options") or []])
    return []


def _collect_basic_attr_options_for_ai(page: Any, label: str, component: str) -> list[str]:
    if component == "checkbox-group":
        return _collect_basic_checkbox_options(page, label)
    if component == "ant-select":
        return _collect_basic_select_options_by_wheel(page, label)
    return []


def _matching_basic_option(value: str, options: list[str]) -> str:
    for option in options:
        if _basic_choice_matches(option, [value]) or _basic_choice_matches(value, [option]):
            return option
    return ""


def _fallback_basic_option_from_options(
    label: str,
    options: list[str],
    *,
    product_info: dict[str, Any] | None = None,
    ai_value: str = "",
) -> str:
    safe_options = _safe_basic_attr_options([str(item) for item in options])
    if not safe_options:
        return ""
    contains_redline = BASE.get("_contains_redline")
    if callable(contains_redline):
        safe_options = [item for item in safe_options if not contains_redline(item)]
    if not safe_options:
        return ""

    label_key = _basic_attr_label_key(label)
    context_text = " ".join(
        str((product_info or {}).get(key) or "")
        for key in ("category", "categoryPath", "title", "englishTitle")
    )
    preference_groups: list[list[str]] = []
    if any(word in label_key for word in ("材料", "材质", "组成", "成分")):
        if any(word in context_text for word in ("毛巾", "浴巾", "沙滩巾", "纺织", "布")):
            preference_groups.append(["超细纤维", "聚酯", "涤纶", "化纤", "纺织", "雪尼尔", "摇粒绒", "抓绒", "丝绒", "缎面", "亚麻", "羊毛", "人造皮革"])
        preference_groups.append(["其他", "超细纤维", "聚酯", "涤纶", "化纤", "纺织", "合成", "雪尼尔", "摇粒绒", "抓绒", "丝绒", "缎面", "亚麻", "羊毛", "人造皮革"])
    elif any(word in label_key for word in ("图案", "风格", "形状", "特征", "类型")):
        preference_groups.append(["其他", "默认", "现代", "简约", "长方形", "通用", "普通"])
    else:
        preference_groups.append(["其他", "默认", "通用", "普通"])

    normalized_ai = _basic_choice_key(ai_value)
    if normalized_ai:
        for option in safe_options:
            option_key = _basic_choice_key(option)
            if option_key and (option_key in normalized_ai or normalized_ai in option_key):
                return option

    for group in preference_groups:
        for keyword in group:
            keyword_key = _basic_choice_key(keyword)
            for option in safe_options:
                option_key = _basic_choice_key(option)
                if keyword_key and option_key and keyword_key in option_key:
                    return option
    return safe_options[0]


def _clean_basic_input_ai_value(label: str, value: Any) -> str:
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split()).strip()
    text = text.strip("\"'`，,。；;：:")
    if not text:
        return ""
    if text.lower() in {"null", "none", "n/a", "na", "unknown"} or text in {"不确定", "未知", "无"}:
        return ""
    contains_redline = BASE.get("_contains_redline")
    if callable(contains_redline) and contains_redline(text):
        return ""
    return text[:80].strip()


def _decide_basic_input_attrs_with_ai(context: dict[str, Any], fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    call_json = BASE.get("_call_laozhang_json")
    if not callable(call_json) or not fields:
        return []
    batch_rules = BASE.get("_batch_rules_active")
    messages = [
        {
            "role": "system",
            "content": (
                "你是 Temu 商品属性文本输入框填写助手。任务是给必填文本输入框生成简短、保守、通用且安全的值。"
                "有批次规则或字段默认规则时遵守规则；没有规则时，根据商品标题、类目、字段名、字段单位/占位自行判断。"
                "严禁输出或暗示红线：液体、带电、电池、锂电、棉、纯棉、棉花、棉质、含棉。"
                "不要编造夸张参数；不确定时给保守通用值，仍不确定则 value 返回 null。"
                "只返回 JSON：{\"decisions\":[{\"label\":\"字段名\",\"value\":\"文本值或null\",\"confidence\":0.0,\"reason\":\"简短理由\"}]}"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "productContext": context,
                    "requiredEmptyInputFields": fields,
                    "localRedlineTerms": BASE.get("REDLINE_ATTR_TERMS") or [],
                    "batchRules": batch_rules() if callable(batch_rules) else {},
                    "preference": [
                        "文本值要短，适合直接填入页面输入框",
                        "重量、克重、尺寸、数量等字段优先输出数字或数字+页面字段单位",
                        "材质/属性描述优先选择安全宽泛表述，避免红线词",
                        "不要输出解释、单位推理或多余句子",
                    ],
                },
                ensure_ascii=False,
            ),
        },
    ]
    result = call_json(messages)
    decisions = result.get("decisions", []) if isinstance(result, dict) else []
    return decisions if isinstance(decisions, list) else []


def _fill_basic_product_attr_missing_by_ai_legacy(robot: Any, page: Any, scan: dict[str, Any] | None = None) -> dict[str, Any]:
    scan_js = (BASE.get("LEGACY") or {}).get("BASIC_ATTR_SCAN_JS") if isinstance(BASE.get("LEGACY"), dict) else None
    if scan is None:
        if not isinstance(scan_js, str) or not scan_js.strip():
            return {"ok": True, "applied": [], "skipped": [], "reason": "missing_scan_js"}
        scan = page.evaluate(scan_js)
    if not isinstance(scan, dict) or not scan.get("ok"):
        return {"ok": False, "applied": [], "skipped": [], "reason": scan}

    attr_has_value = BASE.get("_attr_has_value")
    fields: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for attr in scan.get("attrs") or []:
        if not isinstance(attr, dict):
            continue
        label = str(attr.get("label") or "").strip()
        component = str(attr.get("component") or "").strip()
        if not label or attr.get("visible") is False or not attr.get("required"):
            continue
        if _is_optional_basic_attr_label(label):
            continue
        if component not in {"ant-select", "checkbox-group"}:
            continue
        has_value = bool(attr_has_value(attr)) if callable(attr_has_value) else bool(str(attr.get("value") or "").strip())
        if has_value:
            continue
        options = _collect_basic_attr_options_for_ai(page, label, component)
        if not options:
            if force and _basic_attr_value_is_meaningful(current_value):
                choice_fields.append({"label": label, "component": component, "value": "", "options": [current_value], "current": current_value, "force": force})
                continue
            skipped.append({"label": label, "component": component, "reason": "no_safe_options"})
            _log("WARN", "AI 产品属性缺少安全候选项，已跳过", field=label)
            continue
        fields.append({"label": label, "component": component, "value": "", "options": options[:80]})

    if not fields:
        return {"ok": True, "applied": [], "skipped": skipped, "reason": "no_ai_fields"}

    context_fn = BASE.get("_basic_product_context")
    decide_fn = BASE.get("_decide_basic_attrs_with_ai")
    if not callable(decide_fn):
        skipped.extend({"label": field["label"], "reason": "missing_ai_decider"} for field in fields)
        return {"ok": True, "applied": [], "skipped": skipped}
    try:
        if callable(context_fn):
            try:
                context = context_fn(page, scan)
            except TypeError:
                context = context_fn(page)
        else:
            context = {}
        decisions = decide_fn(context if isinstance(context, dict) else {}, fields)
    except Exception as exc:
        skipped.extend({"label": field["label"], "reason": _safe_error_text(exc)} for field in fields)
        _log("WARN", "AI 产品属性决策失败", error=_safe_error_text(exc))
        return {"ok": True, "applied": [], "skipped": skipped}

    decision_map: dict[str, dict[str, Any]] = {}
    for item in decisions if isinstance(decisions, list) else []:
        if isinstance(item, dict):
            decision_map[str(item.get("label") or "").strip()] = item

    contains_redline = BASE.get("_contains_redline")
    applied: list[dict[str, Any]] = []
    for field in fields:
        label = str(field.get("label") or "")
        decision = decision_map.get(label) or {}
        raw_value = str(decision.get("value") or "").strip()
        if not raw_value:
            skipped.append({"label": label, "reason": "ai_returned_null", "decision": decision})
            continue
        if callable(contains_redline) and contains_redline(raw_value):
            skipped.append({"label": label, "reason": "ai_redline_blocked", "value": raw_value})
            continue
        options = [str(item) for item in field.get("options") or []]
        chosen = _matching_basic_option(raw_value, options)
        if not chosen:
            fallback = _fallback_basic_option_from_options(label, options, product_info=scan.get("productInfo") if isinstance(scan.get("productInfo"), dict) else {}, ai_value=raw_value)
            if fallback:
                skipped.append({"label": label, "reason": "ai_value_not_in_options_used_safe_fallback", "value": raw_value, "fallback": fallback, "options": field.get("options")})
                chosen = fallback
                _log("WARN", "AI 产品属性值不在候选，使用安全候选兜底", field=label, aiValue=raw_value, fallback=fallback)
            else:
                skipped.append({"label": label, "reason": "ai_value_not_in_options", "value": raw_value, "options": field.get("options")})
                continue
        if callable(contains_redline) and contains_redline(chosen):
            skipped.append({"label": label, "reason": "chosen_redline_blocked", "value": chosen})
            continue
        component = str(field.get("component") or "")
        if component == "checkbox-group":
            clicked = page.evaluate(STRICT_CLICK_BASIC_ATTR_CHECKBOX_BY_LABEL_JS, {"label": label, "value": chosen})
            result: dict[str, Any] = {"ok": bool(clicked), "method": "ai-checkbox", "value": chosen}
        else:
            result = _fill_basic_product_attr_select_by_mouse(page, label, [chosen], force=True)
        if isinstance(result, dict) and result.get("ok"):
            applied.append({"label": label, "value": chosen, "component": component, "decision": decision, "result": result})
            _log("OK", "AI 产品属性已填写", field=label, value=chosen, confidence=decision.get("confidence", ""))
        else:
            skipped.append({"label": label, "value": chosen, "reason": result})
            _log("WARN", "AI 产品属性填写失败", field=label, value=chosen, result=result)

    payload = {"ok": True, "applied": applied, "skipped": skipped, "fields": fields}
    if applied or skipped:
        _save_json("basic-product-attr-ai-fill", payload)
    return payload


def _fill_basic_product_attr_missing_by_ai(robot: Any, page: Any, scan: dict[str, Any] | None = None) -> dict[str, Any]:
    scan_js = (BASE.get("LEGACY") or {}).get("BASIC_ATTR_SCAN_JS") if isinstance(BASE.get("LEGACY"), dict) else None
    if scan is None:
        if not isinstance(scan_js, str) or not scan_js.strip():
            return {"ok": True, "applied": [], "skipped": [], "reason": "missing_scan_js"}
        scan = page.evaluate(scan_js)
    if not isinstance(scan, dict) or not scan.get("ok"):
        return {"ok": False, "applied": [], "skipped": [], "reason": scan}

    attr_has_value = BASE.get("_attr_has_value")
    choice_fields: list[dict[str, Any]] = []
    input_fields: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    frontend_error_text = _frontend_error_text_for_basic_attr(page)

    for attr in scan.get("attrs") or []:
        if not isinstance(attr, dict):
            continue
        label = str(attr.get("label") or "").strip()
        component = str(attr.get("component") or "").strip()
        if not label or attr.get("visible") is False or not attr.get("required"):
            continue
        if _is_optional_basic_attr_label(label):
            continue
        if component not in {"input", "ant-select", "checkbox-group"}:
            continue
        current_value = str(attr.get("value") or "").strip()
        has_value = bool(attr_has_value(attr)) if callable(attr_has_value) else _basic_attr_value_is_meaningful(current_value)
        force = _text_mentions_label(frontend_error_text, label)
        if has_value and not force:
            continue
        if component == "input":
            input_fields.append(
                {
                    "label": label,
                    "component": component,
                    "value": "",
                    "placeholder": str(attr.get("placeholder") or ""),
                    "current": current_value,
                    "inputMode": "free_text",
                    "force": force,
                }
            )
            continue
        options = _collect_basic_attr_options_for_ai(page, label, component)
        if not options:
            if force and _basic_attr_value_is_meaningful(current_value):
                choice_fields.append({"label": label, "component": component, "value": "", "options": [current_value], "current": current_value, "force": force})
                continue
            skipped.append({"label": label, "component": component, "reason": "no_safe_options"})
            _log("WARN", "AI 产品属性缺少安全候选项，已跳过", field=label)
            continue
        choice_fields.append({"label": label, "component": component, "value": "", "options": options[:80], "current": current_value, "force": force})

    applied: list[dict[str, Any]] = []
    cache_result = _apply_product_attr_session_cache(page, scan, choice_fields, input_fields)
    if isinstance(cache_result, dict):
        cache_applied = cache_result.get("applied")
        cache_skipped = cache_result.get("skipped")
        if isinstance(cache_applied, list):
            applied.extend(item for item in cache_applied if isinstance(item, dict))
        if isinstance(cache_skipped, list):
            skipped.extend(item for item in cache_skipped if isinstance(item, dict))

    if not choice_fields and not input_fields:
        payload = {"ok": True, "applied": applied, "skipped": skipped, "reason": "session_cache_or_no_ai_fields"}
        if applied or skipped:
            _save_json("basic-product-attr-ai-fill", payload)
        return payload

    context_fn = BASE.get("_basic_product_context")
    try:
        if callable(context_fn):
            try:
                context = context_fn(page, scan)
            except TypeError:
                context = context_fn(page)
        else:
            context = {}
    except Exception as exc:
        context = {}
        _log("WARN", "AI 产品属性上下文读取失败，改用空上下文", error=_safe_error_text(exc))

    decisions: list[dict[str, Any]] = []
    decide_fn = BASE.get("_decide_basic_attrs_with_ai")
    if choice_fields:
        if callable(decide_fn):
            try:
                decisions.extend(decide_fn(context if isinstance(context, dict) else {}, choice_fields))
            except Exception as exc:
                skipped.extend({"label": field["label"], "reason": _safe_error_text(exc)} for field in choice_fields)
                _log("WARN", "AI 产品属性候选项决策失败", error=_safe_error_text(exc))
        else:
            skipped.extend({"label": field["label"], "reason": "missing_ai_decider"} for field in choice_fields)
    if input_fields:
        try:
            decisions.extend(_decide_basic_input_attrs_with_ai(context if isinstance(context, dict) else {}, input_fields))
        except Exception as exc:
            skipped.extend({"label": field["label"], "reason": _safe_error_text(exc)} for field in input_fields)
            _log("WARN", "AI 产品属性文本框决策失败", error=_safe_error_text(exc))

    decision_map: dict[str, dict[str, Any]] = {}
    for item in decisions if isinstance(decisions, list) else []:
        if isinstance(item, dict):
            decision_map[str(item.get("label") or "").strip()] = item

    contains_redline = BASE.get("_contains_redline")
    product_info = scan.get("productInfo") if isinstance(scan.get("productInfo"), dict) else {}

    for field in [*choice_fields, *input_fields]:
        label = str(field.get("label") or "")
        component = str(field.get("component") or "")
        decision = decision_map.get(label) or {}
        raw_value = str(decision.get("value") or "").strip()
        current_field_value = str(field.get("current") or "").strip()
        if not raw_value and _basic_attr_value_is_meaningful(current_field_value):
            raw_value = current_field_value
        if not raw_value:
            skipped.append({"label": label, "reason": "ai_returned_null", "decision": decision})
            continue
        if callable(contains_redline) and contains_redline(raw_value):
            skipped.append({"label": label, "reason": "ai_redline_blocked", "value": raw_value})
            continue

        if component == "input":
            chosen = _clean_basic_input_ai_value(label, raw_value)
            if not chosen:
                skipped.append({"label": label, "reason": "ai_input_value_blocked", "value": raw_value})
                continue
            unit = _basic_input_attr_rule_unit(label, product_info)
            result = page.evaluate(BASIC_ATTR_SET_INPUT_BY_LABEL_JS, {"label": label, "value": chosen, "unit": unit})
            current_value = _read_basic_attr_value(page, label)
            if isinstance(result, dict) and result.get("ok") and _basic_attr_value_is_meaningful(current_value or chosen):
                applied.append({"label": label, "value": current_value or chosen, "component": component, "decision": decision, "result": result})
                _log("OK", "AI 产品属性文本框已填写", field=label, value=current_value or chosen, confidence=decision.get("confidence", ""))
            else:
                skipped.append({"label": label, "value": chosen, "reason": result, "current": current_value})
                _log("WARN", "AI 产品属性文本框填写失败", field=label, value=chosen, result=result, current=current_value)
            continue

        options = [str(item) for item in field.get("options") or []]
        chosen = _matching_basic_option(raw_value, options)
        if not chosen:
            fallback = _fallback_basic_option_from_options(label, options, product_info=product_info, ai_value=raw_value)
            if fallback:
                skipped.append({"label": label, "reason": "ai_value_not_in_options_used_safe_fallback", "value": raw_value, "fallback": fallback, "options": field.get("options")})
                chosen = fallback
                _log("WARN", "AI 产品属性值不在候选，使用安全候选兜底", field=label, aiValue=raw_value, fallback=fallback)
            else:
                skipped.append({"label": label, "reason": "ai_value_not_in_options", "value": raw_value, "options": field.get("options")})
                continue
        if callable(contains_redline) and contains_redline(chosen):
            skipped.append({"label": label, "reason": "chosen_redline_blocked", "value": chosen})
            continue
        if component == "checkbox-group":
            clicked = page.evaluate(STRICT_CLICK_BASIC_ATTR_CHECKBOX_BY_LABEL_JS, {"label": label, "value": chosen})
            result: dict[str, Any] = {"ok": bool(clicked), "method": "ai-checkbox", "value": chosen}
        else:
            result = _fill_basic_product_attr_select_by_mouse(page, label, [chosen], force=True)
        if isinstance(result, dict) and result.get("ok"):
            applied.append({"label": label, "value": chosen, "component": component, "decision": decision, "result": result})
            _log("OK", "AI 产品属性已填写", field=label, value=chosen, confidence=decision.get("confidence", ""))
        else:
            skipped.append({"label": label, "value": chosen, "reason": result})
            _log("WARN", "AI 产品属性填写失败", field=label, value=chosen, result=result)

    payload = {"ok": True, "applied": applied, "skipped": skipped, "fields": [*choice_fields, *input_fields]}
    _record_product_attr_session_cache(scan, applied, source="ai_or_session")
    if applied or skipped:
        _save_json("basic-product-attr-ai-fill", payload)
    return payload


def _fill_basic_product_attr_select_by_wheel(page: Any, label: str, candidates: list[str], *, force: bool = False) -> dict[str, Any]:
    box_js = BASE.get("GET_BASIC_ATTR_SELECT_BOX_BY_LABEL_JS")
    if not isinstance(box_js, str) or not box_js.strip():
        box_js = STRICT_GET_BASIC_ATTR_SELECT_BOX_BY_LABEL_JS
    try:
        box = page.evaluate(box_js, label)
    except Exception as exc:
        return {"ok": False, "method": "wheel", "error": "select_box_exception", "message": _safe_error_text(exc)}
    if not isinstance(box, dict) or not box.get("ok"):
        return {"ok": False, "method": "wheel", "error": "select_box_not_found", "box": box}

    x = float(box.get("x") or 0) + float(box.get("w") or 0) / 2
    y = float(box.get("y") or 0) + float(box.get("h") or 0) / 2
    all_seen: list[str] = []
    last_signature = ""
    stagnant_rounds = 0
    last_state: dict[str, Any] | None = None

    for open_attempt in range(2):
        try:
            _close_active_dropdowns_for_basic_attrs(page)
            time.sleep(0.08)
            page.mouse.click(x, y)
            time.sleep(0.25)
        except Exception as exc:
            return {"ok": False, "method": "wheel", "error": "open_dropdown_failed", "message": _safe_error_text(exc), "box": box}

        for step in range(24):
            try:
                state = page.evaluate(
                    BASIC_ATTR_VISIBLE_DROPDOWN_OPTION_POINTS_JS,
                    {"box": box, "candidates": candidates},
                )
            except Exception as exc:
                return {"ok": False, "method": "wheel", "error": "read_dropdown_failed", "message": _safe_error_text(exc), "box": box}
            last_state = state if isinstance(state, dict) else {"value": state}
            if isinstance(state, dict):
                for item in state.get("seen") or []:
                    text = str(item or "").strip()
                    if text and text not in all_seen:
                        all_seen.append(text)
                point = state.get("point") if state.get("ok") else None
                if isinstance(point, dict) and point.get("x") is not None and point.get("y") is not None:
                    try:
                        page.mouse.click(float(point["x"]), float(point["y"]))
                        time.sleep(0.3)
                    except Exception as exc:
                        return {"ok": False, "method": "wheel", "error": "click_option_failed", "message": _safe_error_text(exc), "state": state}
                    current_value = _read_basic_attr_value(page, label)
                    if _basic_choice_matches(current_value, candidates) or not force:
                        return {
                            "ok": True,
                            "method": "wheel",
                            "label": label,
                            "value": current_value or str(state.get("text") or ""),
                            "chosen": str(state.get("text") or ""),
                            "seen": all_seen,
                            "scrollSteps": step,
                            "openAttempt": open_attempt + 1,
                        }
                dropdown_box = state.get("dropdownBox")
                if not isinstance(dropdown_box, dict):
                    break
                signature = "|".join(str(item) for item in state.get("seen") or [])
                if signature == last_signature:
                    stagnant_rounds += 1
                else:
                    stagnant_rounds = 0
                    last_signature = signature
                if state.get("atEnd") and stagnant_rounds >= 1:
                    break
                try:
                    sx = float(dropdown_box.get("x") or 0) + float(dropdown_box.get("w") or 0) / 2
                    sy = float(dropdown_box.get("y") or 0) + min(float(dropdown_box.get("h") or 0) - 12, 160)
                    page.mouse.move(sx, sy)
                    page.mouse.wheel(0, 420)
                    time.sleep(0.16)
                except Exception as exc:
                    return {"ok": False, "method": "wheel", "error": "wheel_failed", "message": _safe_error_text(exc), "state": state}
    return {
        "ok": False,
        "method": "wheel",
        "error": "option_not_found_after_wheel",
        "label": label,
        "candidates": candidates,
        "seen": all_seen,
        "lastState": last_state,
    }


def _fill_basic_product_attr_select_by_mouse(page: Any, label: str, candidates: list[str], *, force: bool = False) -> dict[str, Any]:
    wheel_result = _fill_basic_product_attr_select_by_wheel(page, label, candidates, force=force)
    if isinstance(wheel_result, dict) and wheel_result.get("ok"):
        return wheel_result
    current_value = _read_basic_attr_value(page, label)
    if _basic_choice_matches(current_value, candidates):
        return {
            "ok": True,
            "method": "wheel-confirmed-after-fail",
            "label": label,
            "chosen": candidates[0] if candidates else "",
            "value": current_value,
            "wheelResult": wheel_result,
            "force": force,
        }
    fill_select = BASE.get("_fill_basic_select_attr")
    errors: list[str] = []
    if callable(fill_select):
        for candidate in candidates:
            try:
                _close_active_dropdowns_for_basic_attrs(page)
                if fill_select(page, label, candidate):
                    current_value = _read_basic_attr_value(page, label)
                    return {
                        "ok": True,
                        "method": "mouse",
                        "label": label,
                        "chosen": candidate,
                        "value": current_value or candidate,
                        "force": force,
                    }
                current_value = _read_basic_attr_value(page, label)
                if _basic_choice_matches(current_value, candidates):
                    return {
                        "ok": True,
                        "method": "mouse-confirmed",
                        "label": label,
                        "chosen": candidate,
                        "value": current_value,
                        "force": force,
                    }
            except Exception as exc:
                errors.append(f"{candidate}: {_safe_error_text(exc)}")
    try:
        result = page.evaluate(
            BASIC_ATTR_SELECT_BY_LABEL_JS,
            {"label": label, "candidates": candidates, "force": force},
        )
        if isinstance(result, dict):
            result.setdefault("method", "dom")
            result["wheelResult"] = wheel_result
            if errors:
                result["mouseErrors"] = errors[:5]
            if not result.get("ok"):
                current_value = _read_basic_attr_value(page, label)
                if _basic_choice_matches(current_value, candidates):
                    result.update({"ok": True, "method": "dom-confirmed-after-fail", "value": current_value})
            return result
        return {"ok": False, "error": "unexpected_dom_result", "result": result, "wheelResult": wheel_result, "mouseErrors": errors[:5]}
    except Exception as exc:
        return {"ok": False, "error": "dom_select_exception", "message": _safe_error_text(exc), "wheelResult": wheel_result, "mouseErrors": errors[:5]}


def _fill_basic_product_attr_selects_by_rule(page: Any, scan: dict[str, Any] | None = None) -> dict[str, Any]:
    scan_js = (BASE.get("LEGACY") or {}).get("BASIC_ATTR_SCAN_JS") if isinstance(BASE.get("LEGACY"), dict) else None
    if scan is None:
        if not isinstance(scan_js, str) or not scan_js.strip():
            return {"ok": True, "applied": [], "skipped": [], "reason": "missing_scan_js"}
        scan = page.evaluate(scan_js)
    if not isinstance(scan, dict) or not scan.get("ok"):
        return {"ok": False, "applied": [], "skipped": [], "reason": scan}
    product_info = scan.get("productInfo") if isinstance(scan.get("productInfo"), dict) else {}
    attr_has_value = BASE.get("_attr_has_value")
    frontend_error_text = _frontend_error_text_for_basic_attr(page)
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for attr in scan.get("attrs") or []:
        if not isinstance(attr, dict):
            continue
        label = str(attr.get("label") or "").strip()
        if not label or attr.get("visible") is False:
            continue
        if _is_optional_basic_attr_label(label):
            continue
        if attr.get("component") != "ant-select":
            continue
        if not attr.get("required") and not _text_mentions_label(frontend_error_text, label):
            continue
        has_value = bool(attr_has_value(attr)) if callable(attr_has_value) else bool(str(attr.get("value") or "").strip())
        force = _text_mentions_label(frontend_error_text, label)
        if has_value and not force:
            continue
        candidates = _basic_select_attr_rule_candidates(label, product_info)
        if not candidates:
            skipped.append({"label": label, "reason": "await_ai_fallback"})
            continue
        result = _fill_basic_product_attr_select_by_mouse(page, label, candidates, force=force)
        if isinstance(result, dict) and result.get("ok"):
            if not result.get("skipped"):
                applied.append({"label": label, "candidates": candidates, "result": result})
                _log("OK", "产品属性下拉已填写", field=label, value=result.get("value") or result.get("chosen") or "")
        else:
            skipped.append({"label": label, "candidates": candidates, "reason": result})
            _log("WARN", "产品属性下拉填写失败", field=label, candidates="|".join(candidates), result=result)
    if applied:
        refreshed = page.evaluate(scan_js) if isinstance(scan_js, str) and scan_js.strip() else scan
        _fill_basic_product_attr_percent_by_rule(page, refreshed if isinstance(refreshed, dict) else None)
    payload = {"ok": True, "applied": applied, "skipped": skipped}
    if applied or skipped:
        _save_json("basic-product-attr-select-fill", payload)
    return payload


def _fill_basic_product_attr_percent_by_rule(page: Any, scan: dict[str, Any] | None = None) -> dict[str, Any]:
    scan_js = (BASE.get("LEGACY") or {}).get("BASIC_ATTR_SCAN_JS") if isinstance(BASE.get("LEGACY"), dict) else None
    if scan is None:
        if not isinstance(scan_js, str) or not scan_js.strip():
            return {"ok": True, "applied": [], "skipped": [], "reason": "missing_scan_js"}
        scan = page.evaluate(scan_js)
    if not isinstance(scan, dict) or not scan.get("ok"):
        return {"ok": False, "applied": [], "skipped": [], "reason": scan}
    attr_has_value = BASE.get("_attr_has_value")
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for attr in scan.get("attrs") or []:
        if not isinstance(attr, dict):
            continue
        label = str(attr.get("label") or "").strip()
        if "成分" not in label:
            continue
        has_value = bool(attr_has_value(attr)) if callable(attr_has_value) else bool(str(attr.get("value") or "").strip())
        if not has_value:
            skipped.append({"label": label, "reason": "成分未选择"})
            continue
        result = page.evaluate(BASIC_ATTR_SET_PERCENT_BY_LABEL_JS, {"label": label, "percent": "100"})
        if isinstance(result, dict) and result.get("ok"):
            applied.append({"label": label, "percent": "100", "result": result})
            if result.get("changed"):
                _log("OK", "产品属性成分百分比已填写", field=label, percent="100")
        else:
            skipped.append({"label": label, "percent": "100", "reason": result})
            _log("WARN", "产品属性成分百分比填写失败", field=label, result=result)
    payload = {"ok": True, "applied": applied, "skipped": skipped}
    if applied or skipped:
        _save_json("basic-product-attr-percent-fill", payload)
    return payload


def _fill_basic_product_attr_inputs_by_rule(page: Any) -> dict[str, Any]:
    scan_js = (BASE.get("LEGACY") or {}).get("BASIC_ATTR_SCAN_JS") if isinstance(BASE.get("LEGACY"), dict) else None
    if not isinstance(scan_js, str) or not scan_js.strip():
        return {"ok": True, "applied": [], "skipped": [], "reason": "missing_scan_js"}
    scan = page.evaluate(scan_js)
    if not isinstance(scan, dict) or not scan.get("ok"):
        raise RuntimeError(f"产品属性文本框扫描失败：{scan}")
    product_info = scan.get("productInfo") if isinstance(scan.get("productInfo"), dict) else {}
    attr_has_value = BASE.get("_attr_has_value")
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for attr in scan.get("attrs") or []:
        if not isinstance(attr, dict):
            continue
        if attr.get("component") != "input" or not attr.get("required") or attr.get("visible") is False:
            continue
        has_value = bool(attr_has_value(attr)) if callable(attr_has_value) else bool(str(attr.get("value") or "").strip())
        if has_value:
            continue
        label = str(attr.get("label") or "").strip()
        value = _basic_input_attr_rule_value(label, product_info)
        unit = _basic_input_attr_rule_unit(label, product_info)
        if not value:
            skipped.append({"label": label, "reason": "没有文本输入框规则"})
            _log("WARN", "产品属性文本框缺少填写规则，已跳过", field=label)
            continue
        result = page.evaluate(BASIC_ATTR_SET_INPUT_BY_LABEL_JS, {"label": label, "value": value, "unit": unit})
        if isinstance(result, dict) and result.get("ok"):
            applied.append({"label": label, "value": value, "unit": unit, "result": result})
            _log("OK", "产品属性文本框已填写", field=label, value=value, unit=unit or result.get("unit") or "")
        else:
            skipped.append({"label": label, "value": value, "unit": unit, "reason": result})
            _log("WARN", "产品属性文本框填写失败", field=label, value=value, unit=unit, result=result)
    payload = {"ok": True, "applied": applied, "skipped": skipped}
    if applied or skipped:
        _save_json("basic-product-attr-input-fill", payload)
    return payload


def _close_active_dropdowns_for_basic_attrs(page: Any) -> None:
    try:
        page.keyboard.press("Escape")
    except Exception:
        return


def _scroll_basic_product_attrs_into_view(page: Any) -> dict[str, Any]:
    try:
        return page.evaluate(
            """
            () => {
              const norm = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
              const attrRe = /\\u4ea7\\u54c1\\u5c5e\\u6027|\\u5e73\\u65b9\\u514b\\u91cd|\\u6750\\u6599\\u7ec4\\u6210|\\u6210\\u5206|\\u98ce\\u683c|\\u7279\\u5f81|\\u62a4\\u7406\\u8bf4\\u660e|\\u989c\\u8272|\\u6570\\u91cf/;
              const nodes = Array.from(document.querySelectorAll('body *'));
              const matches = nodes
                .map((el) => ({ el, text: norm(el.innerText || el.textContent) }))
                .filter((item) => item.text && item.text.length <= 120 && attrRe.test(item.text))
                .sort((a, b) => a.text.length - b.text.length);
              const productAttrTitle = matches.length ? matches[0].el : null;
              if (productAttrTitle) {
                productAttrTitle.scrollIntoView({ block: 'center', inline: 'nearest' });
                return { ok: true, target: norm(productAttrTitle.innerText || productAttrTitle.textContent).slice(0, 80) };
              }
              return { ok: false };
            }
            """
        )
    except Exception as exc:
        return {"ok": False, "error": _safe_error_text(exc)}


def _scan_basic_product_attrs_strict(
    page: Any,
    *,
    attempts: int = 5,
    delay: float = 0.8,
    table_printer: Any = None,
) -> dict[str, Any]:
    scan_js = (BASE.get("LEGACY") or {}).get("BASIC_ATTR_SCAN_JS") if isinstance(BASE.get("LEGACY"), dict) else None
    if not isinstance(scan_js, str) or not scan_js.strip():
        raise RuntimeError("missing BASIC_ATTR_SCAN_JS for basic product attributes")

    last_result: Any = None
    last_scroll: Any = None
    max_attempts = max(1, int(attempts or 1))
    for attempt in range(1, max_attempts + 1):
        _close_active_dropdowns_for_basic_attrs(page)
        last_scroll = _scroll_basic_product_attrs_into_view(page)
        try:
            page.wait_for_timeout(250)
        except Exception:
            time.sleep(0.25)
        try:
            result = page.evaluate(scan_js)
        except Exception as exc:
            last_result = {"ok": False, "error": _safe_error_text(exc)}
            attrs: list[Any] = []
        else:
            last_result = result
            attrs = result.get("attrs", []) if isinstance(result, dict) else []

        count = len(attrs) if isinstance(attrs, list) else 0
        if isinstance(last_result, dict) and last_result.get("ok") and count > 0:
            _log("INFO", "扫描基本信息商品属性完成", count=count, attempt=attempt)
            if callable(table_printer):
                table_printer(attrs)
            _save_json("basic-info-scan-attrs", last_result)
            return last_result

        if attempt < max_attempts:
            _log(
                "WARN",
                "产品属性扫描未命中，等待页面渲染后重试",
                attempt=attempt,
                nextAttempt=attempt + 1,
                count=count,
                scroll=last_scroll,
            )
            time.sleep(max(0.1, float(delay or 0.1)))

    payload = {"ok": False, "lastResult": last_result, "scroll": last_scroll, "attempts": max_attempts}
    _save_json("basic-info-scan-attrs-empty", payload)
    raise RuntimeError(f"扫描基本信息商品属性失败：连续 {max_attempts} 次未找到产品属性字段")


def _fill_basic_required_attrs_ai_guarded_with_product_attr_rules(robot: Any, page: Any, max_rounds: int = 4) -> dict[str, Any]:
    rounds: list[dict[str, Any]] = []
    input_result: dict[str, Any] = {"ok": True, "applied": [], "skipped": []}
    select_result: dict[str, Any] = {"ok": True, "applied": [], "skipped": []}
    percent_result: dict[str, Any] = {"ok": True, "applied": [], "skipped": []}
    ai_result: dict[str, Any] = {"ok": True, "applied": [], "skipped": []}
    cache_result: dict[str, Any] = {"ok": True, "applied": [], "skipped": []}

    def count_applied(payload: Any) -> int:
        if not isinstance(payload, dict):
            return 0
        applied = payload.get("applied")
        return len(applied) if isinstance(applied, list) else 0

    last_missing: list[str] = []
    for round_index in range(1, max(1, int(max_rounds or 1)) + 1):
        _close_active_dropdowns_for_basic_attrs(page)
        try:
            before_missing = _basic_attr_missing_required(page)
        except Exception:
            before_missing = []
        try:
            current_scan = page.evaluate((BASE.get("LEGACY") or {}).get("BASIC_ATTR_SCAN_JS"))
        except Exception:
            current_scan = None
        try:
            cache_result = _fill_basic_product_attrs_from_session_cache(page, current_scan if isinstance(current_scan, dict) else None)
        except Exception as exc:
            cache_result = {
                "ok": True,
                "applied": [],
                "skipped": [{"reason": "session_cache_exception_continue_ai", "error": _safe_error_text(exc)}],
                "reason": "session_cache_exception_continue_ai",
            }
            _log("WARN", "产品属性会话缓存异常，继续固定规则和 AI 降级", error=_safe_error_text(exc))
        input_result = _fill_basic_product_attr_inputs_by_rule(page)
        select_result = _fill_basic_product_attr_selects_by_rule(page)
        percent_result = _fill_basic_product_attr_percent_by_rule(page)
        try:
            refreshed_scan = page.evaluate((BASE.get("LEGACY") or {}).get("BASIC_ATTR_SCAN_JS"))
        except Exception:
            refreshed_scan = None
        ai_result = _fill_basic_product_attr_missing_by_ai(robot, page, refreshed_scan if isinstance(refreshed_scan, dict) else None)
        percent_result = _fill_basic_product_attr_percent_by_rule(page)
        _close_active_dropdowns_for_basic_attrs(page)
        time.sleep(0.25)
        try:
            after_missing = _basic_attr_missing_required(page)
        except Exception:
            after_missing = []
        try:
            after_scan = page.evaluate((BASE.get("LEGACY") or {}).get("BASIC_ATTR_SCAN_JS"))
            _record_product_attr_session_cache_from_scan(after_scan if isinstance(after_scan, dict) else None, source="visible_scan")
        except Exception as exc:
            _log("WARN", "产品属性会话缓存整页记录失败", error=_safe_error_text(exc))
        applied_count = count_applied(cache_result) + count_applied(input_result) + count_applied(select_result) + count_applied(percent_result) + count_applied(ai_result)
        rounds.append(
            {
                "round": round_index,
                "beforeMissing": before_missing,
                "afterMissing": after_missing,
                "appliedCount": applied_count,
                "cache": cache_result,
                "input": input_result,
                "select": select_result,
                "ai": ai_result,
                "percent": percent_result,
            }
        )
        last_missing = after_missing
        if not after_missing:
            break
        if applied_count <= 0 and after_missing == before_missing:
            break
        _log("INFO", "产品属性联动字段复扫", round=round_index, missing="|".join(after_missing))
    return {
        "ok": True,
        "mode": "product_attrs_required_only",
        "rounds": rounds,
        "missingRequired": last_missing,
        "cache": cache_result,
        "input": input_result,
        "select": select_result,
        "ai": ai_result,
        "percent": percent_result,
    }


BASE["_fill_basic_required_attrs_ai_guarded"] = _fill_basic_required_attrs_ai_guarded_with_product_attr_rules


def _skip_basic_age_range_rule(page: Any) -> dict[str, Any]:
    return {"ok": True, "skipped": True, "reason": "product_attrs_required_only"}


def fill_basic_required_attrs_product_attrs_only(self: Any) -> Any:
    self.ensure_connected()
    if hasattr(self, "bind_edit_page"):
        self.bind_edit_page()
    page = self.page
    _log("INFO", "开始填写基本信息产品属性", scope="仅产品属性")
    _scan_basic_product_attrs_strict(page, attempts=5, delay=0.8)
    ai_guarded = BASE.get("_fill_basic_required_attrs_ai_guarded")
    result = ai_guarded(self, page) if callable(ai_guarded) else None
    return result


def scan_basic_attrs_product_attrs_only(self: Any) -> Any:
    self.ensure_connected()
    if hasattr(self, "bind_edit_page"):
        self.bind_edit_page()
    page = self.page
    return _scan_basic_product_attrs_strict(
        page,
        attempts=5,
        delay=0.8,
        table_printer=getattr(self, "print_attr_table", None),
    )


def _basic_attr_missing_required(page: Any) -> list[str]:
    scan_js = (BASE.get("LEGACY") or {}).get("BASIC_ATTR_SCAN_JS") if isinstance(BASE.get("LEGACY"), dict) else None
    if not isinstance(scan_js, str) or not scan_js.strip():
        return []
    try:
        scan = page.evaluate(scan_js)
    except Exception as exc:
        _log("WARN", "基本信息必填复检失败", error=_safe_error_text(exc))
        return []
    if not isinstance(scan, dict) or not scan.get("ok"):
        return []
    missing: list[str] = []
    attr_has_value = BASE.get("_attr_has_value")
    for attr in scan.get("attrs") or []:
        if not isinstance(attr, dict):
            continue
        if not attr.get("required") or attr.get("visible") is False:
            continue
        has_value = bool(attr_has_value(attr)) if callable(attr_has_value) else bool(str(attr.get("value") or "").strip())
        if has_value:
            continue
        label = str(attr.get("label") or "").strip()
        if _is_optional_basic_attr_label(label):
            continue
        if label:
            missing.append(label)
    return missing


def _frontend_required_errors(page: Any, *, product_attrs_only: bool = False) -> list[dict[str, str]]:
    try:
        value = page.evaluate(PRODUCT_ATTR_REQUIRED_ERRORS_JS if product_attrs_only else FRONTEND_REQUIRED_ERRORS_JS)
    except Exception as exc:
        _log("WARN", "前台必填错误读取失败", error=_safe_error_text(exc))
        return []
    if not isinstance(value, list):
        return []
    errors: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        label = str(item.get("label") or "").strip()
        item_text = str(item.get("itemText") or "").strip()
        if not text:
            continue
        errors.append({"label": label, "text": text, "itemText": item_text})
    return errors


def _validate_frontend_required_state(robot: Any, step_name: str) -> None:
    if "基本信息" not in step_name:
        return
    if "扫描" in step_name:
        return
    page = getattr(robot, "page", None)
    if page is None:
        return
    missing: list[str] = []
    missing.extend(_basic_attr_missing_required(page))

    frontend_errors = _frontend_required_errors(page, product_attrs_only=True)
    for item in frontend_errors:
        label = item.get("label") or ""
        text = item.get("text") or ""
        item_text = item.get("itemText") or ""
        if _is_optional_basic_attr_label(str(label)):
            continue
        if _frontend_required_error_is_resolved_by_basic_attr_value(
            page,
            label=str(label),
            text=str(text),
            item_text=str(item_text),
        ):
            continue
        if label and text:
            missing.append(f"{label}: {text}")
        elif text:
            hint = item_text[:60] if item_text else ""
            missing.append(f"{text}{(' [' + hint + ']') if hint else ''}")

    if not missing:
        return
    unique: list[str] = []
    seen: set[str] = set()
    for item in missing:
        text = " ".join(str(item).split())
        if not text or text in seen or _is_optional_basic_attr_label(_missing_required_label_text(text)):
            continue
        seen.add(text)
        unique.append(text)
    payload = {"step": step_name, "missingRequired": unique, "frontendErrors": frontend_errors}
    _save_json("frontend-required-errors", payload)
    raise RuntimeError("前台仍有必填错误：" + " | ".join(unique[:8]))


def _unique_child_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{index:03d}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")


def _resolve_download_folder(folder_text: str) -> Path:
    raw = str(folder_text or "").strip()
    candidates: list[Path] = []
    if raw:
        repair = BASE.get("_repair_mojibake_text")
        raw_candidates = repair(raw) if callable(repair) else [raw]
        for text in raw_candidates:
            path = Path(text).expanduser()
            if not path.is_absolute():
                path = (APP_DIR / path).resolve()
            candidates.append(path)
    pipeline_folder = BASE.get("_pipeline_image_folder")
    if callable(pipeline_folder):
        try:
            candidates.append(Path(pipeline_folder(_load_pipeline_config())))
        except Exception:
            pass
    for folder in candidates:
        if folder.exists() and folder.is_dir():
            return folder
    checked = " | ".join(str(path) for path in candidates) or raw
    raise RuntimeError(f"图片下载文件夹不存在：{checked}")


def _image_files(folder: Path) -> list[Path]:
    return [
        path
        for path in sorted(folder.iterdir(), key=lambda item: item.name.lower())
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS
    ]


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = str(value or "#FFFFFF").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except Exception:
        return (255, 255, 255)


def _save_square_image(img: Any, output_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    from PIL import Image, ImageOps

    target = (int(config["targetWidth"]), int(config["targetHeight"]))
    bg = _hex_to_rgb(str(config.get("background") or "#FFFFFF"))
    method = getattr(Image.Resampling, "LANCZOS", Image.LANCZOS)
    img = ImageOps.exif_transpose(img)
    if config.get("mode") == "cover":
        square = ImageOps.fit(img, target, method=method, centering=(0.5, 0.5))
        if square.mode != "RGB":
            canvas = Image.new("RGB", target, bg)
            if "A" in square.getbands():
                canvas.paste(square.convert("RGBA"), (0, 0), square.convert("RGBA").split()[-1])
            else:
                canvas.paste(square.convert("RGB"), (0, 0))
            square = canvas
        else:
            square = square.convert("RGB")
    else:
        contained = ImageOps.contain(img, target, method=method)
        canvas = Image.new("RGB", target, bg)
        x = (target[0] - contained.width) // 2
        y = (target[1] - contained.height) // 2
        if "A" in contained.getbands():
            rgba = contained.convert("RGBA")
            canvas.paste(rgba, (x, y), rgba.split()[-1])
        else:
            canvas.paste(contained.convert("RGB"), (x, y))
        square = canvas

    temp_path = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
    fmt = str(config.get("outputFormat") or "jpg").upper()
    if fmt == "JPG":
        fmt = "JPEG"
    quality_candidates = [int(config["quality"]), 84, 80, 76, 72, 68, 64, 60]
    max_bytes = int(config["maxBytes"])
    last_size = 0
    for quality in quality_candidates:
        save_kwargs: dict[str, Any] = {"format": fmt}
        if fmt in {"JPEG", "WEBP"}:
            save_kwargs.update({"quality": quality, "optimize": True})
        square.save(temp_path, **save_kwargs)
        last_size = temp_path.stat().st_size
        if last_size <= max_bytes or fmt == "PNG":
            break
    temp_path.replace(output_path)
    return {"width": target[0], "height": target[1], "size": output_path.stat().st_size, "quality": quality_candidates[-1] if last_size > max_bytes else quality}


def _postprocess_downloaded_product_images(folder: Path, config: dict[str, Any]) -> dict[str, Any]:
    from PIL import Image

    folder.mkdir(parents=True, exist_ok=True)
    ignored_dir = folder / "_ignored_small_images"
    original_dir = folder / "_original_before_square"
    manifest: list[dict[str, Any]] = []
    processed = 0
    ignored = 0
    failed = 0

    for path in _image_files(folder):
        record: dict[str, Any] = {"name": path.name, "path": str(path)}
        try:
            with Image.open(path) as img:
                src_width, src_height = img.size
                record.update({"sourceWidth": src_width, "sourceHeight": src_height, "sourceSize": path.stat().st_size})
                if src_width < int(config["minSourceWidth"]) or src_height < int(config["minSourceHeight"]):
                    ignored_dir.mkdir(parents=True, exist_ok=True)
                    dest = _unique_child_path(ignored_dir / path.name)
                    img.close()
                    shutil.move(str(path), str(dest))
                    record.update({"status": "ignored_small", "movedTo": str(dest)})
                    ignored += 1
                    manifest.append(record)
                    _log("WARN", "图片太小，已移入忽略目录，避免误传", name=path.name, width=src_width, height=src_height)
                    continue

                suffix = ".jpg" if str(config.get("outputFormat")).lower() in {"jpg", "jpeg"} else f".{config.get('outputFormat')}"
                output_path = path.with_suffix(suffix)
                output_path = output_path if output_path == path else _unique_child_path(output_path)
                output = _save_square_image(img, output_path, config)
                if output_path != path and path.exists():
                    original_dir.mkdir(parents=True, exist_ok=True)
                    img.close()
                    shutil.move(str(path), str(_unique_child_path(original_dir / path.name)))
                record.update({"status": "processed", "output": str(output_path), **output})
                processed += 1
                _log("OK", "图片已压缩为 800x800 方图", name=output_path.name, source=f"{src_width}x{src_height}", size=output.get("size"))
        except Exception as exc:
            failed += 1
            record.update({"status": "failed", "error": _safe_error_text(exc)})
            _log("ERROR", "图片后处理失败", name=path.name, error=_safe_error_text(exc))
        manifest.append(record)

    payload = {
        "ok": failed == 0,
        "folder": str(folder),
        "processed": processed,
        "ignored": ignored,
        "failed": failed,
        "config": config,
        "images": manifest,
    }
    (folder / "image-postprocess-manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _save_json("image-postprocess-run", payload)
    _log("OK", "图片下载后处理完成", folder=str(folder), processed=processed, ignored=ignored, failed=failed)
    if failed:
        raise RuntimeError(f"图片后处理失败 {failed} 张，详情见 {folder / 'image-postprocess-manifest.json'}")
    return payload


_base_bind_edit_page = BASE["LEGACY"]["DxmTemuRobot"].bind_edit_page


def _temu_edit_id(url: str) -> str:
    text = str(url or "").strip()
    if "id=" not in text:
        return ""
    return text.split("id=", 1)[1].split("&", 1)[0].split("#", 1)[0].strip()


def _is_temu_edit_url(url: str) -> bool:
    return "/web/popTemu/edit" in str(url or "")


def _page_matches_requested_edit_url(page_url: str, requested_url: str) -> bool:
    requested_id = _temu_edit_id(requested_url)
    if requested_id:
        return _temu_edit_id(page_url) == requested_id
    requested = str(requested_url or "").strip().rstrip("/")
    current = str(page_url or "").strip().rstrip("/")
    return bool(requested and current and (requested == current or requested in current))


TEMU_EDIT_PAGE_READY_JS = r"""
() => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  const text = clean(document.body && (document.body.innerText || document.body.textContent) || '');
  const found = ['基本信息','产品信息','变种属性','变种信息','产品描述','运输信息'].filter(item => text.includes(item));
  const formReady = !!document.querySelector('input,textarea,.ant-select,#wirelessDescBox,.skuWarehouse');
  return {
    ok: location.href.includes('/web/popTemu/edit') && formReady && found.length >= 2,
    found,
    formReady,
    url: location.href
  };
}
"""


def _wait_temu_edit_page_ready(page: Any, *, timeout: float = 10.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    started = time.time()
    last: dict[str, Any] = {}
    while time.time() < deadline:
        try:
            result = page.evaluate(TEMU_EDIT_PAGE_READY_JS)
            last = result if isinstance(result, dict) else {"raw": result}
            if last.get("ok"):
                last["waitMs"] = int((time.time() - started) * 1000)
                return last
        except Exception as exc:
            last = {"ok": False, "error": _safe_error_text(exc)}
        time.sleep(0.2)
    last["waitMs"] = int((time.time() - started) * 1000)
    return last


def bind_edit_page_prefer_requested(self: Any, url: str = "") -> dict[str, Any]:
    requested_url = str(url or "").strip()
    if not requested_url:
        return _base_bind_edit_page(self, url)

    ensure_connected = getattr(self, "ensure_connected", None)
    if callable(ensure_connected):
        ensure_connected()

    context = getattr(self, "context", None)
    if context is None:
        return _base_bind_edit_page(self, url)

    pages = list(getattr(context, "pages", []) or [])
    for page in pages:
        page_url = str(getattr(page, "url", "") or "")
        if _is_temu_edit_url(page_url) and _page_matches_requested_edit_url(page_url, requested_url):
            self.page = page
            try:
                page.bring_to_front()
            except Exception:
                pass
            _log("OK", "已绑定指定商品编辑页", url=page_url)
            return {"ok": True, "url": page_url, "requestedUrl": requested_url, "reused": True}

    page = next((item for item in pages if _is_temu_edit_url(str(getattr(item, "url", "") or ""))), None)
    if page is None:
        page = context.new_page()
    self.page = page
    try:
        page.bring_to_front()
    except Exception:
        pass
    page.goto(requested_url, wait_until="domcontentloaded", timeout=60000)
    ready = _wait_temu_edit_page_ready(page, timeout=10)
    if ready.get("ok"):
        _log("OK", "编辑页关键表单已就绪", waitMs=ready.get("waitMs"), found="|".join(ready.get("found") or []))
    else:
        _log("WARN", "编辑页关键表单未确认就绪，短暂等待后继续", waitMs=ready.get("waitMs"), state=ready)
        page.wait_for_timeout(800)
    final_url = str(getattr(page, "url", "") or "")
    _log("OK", "已打开并绑定指定商品编辑页", url=final_url)
    return {"ok": True, "url": final_url, "requestedUrl": requested_url, "reused": False}


BASE["LEGACY"]["DxmTemuRobot"].bind_edit_page = bind_edit_page_prefer_requested


def _download_result_folder(download_result: Any, folder_text: str = "") -> Path:
    if isinstance(download_result, dict) and download_result.get("folder"):
        path = Path(str(download_result["folder"])).expanduser()
        if path.exists() and path.is_dir():
            return path
    return _resolve_download_folder(folder_text)


def _uploadable_product_info_image_files(folder: Path) -> list[str]:
    files = [str(path) for path in _image_files(folder)[:10]]
    if not files:
        raise RuntimeError(f"没有可上传的本地图片：{folder}")
    if len(files) < 3:
        _log("WARN", "产品信息图片少于 3 张，仍继续上传", count=len(files), folder=str(folder))
    return files


def _click_product_info_action(page: Any, labels: list[str], *, exact: bool = False, timeout: float = 10.0) -> dict[str, Any]:
    click_point = BASE.get("_click_point")
    if not callable(click_point):
        raise RuntimeError("缺少坐标点击函数，无法操作产品信息图片")
    deadline = time.time() + timeout
    last: dict[str, Any] = {}
    while time.time() < deadline:
        point = page.evaluate(PRODUCT_INFO_FIND_ACTION_POINT_JS, {"labels": labels, "exact": exact})
        last = point if isinstance(point, dict) else {}
        if last.get("ok"):
            click_point(page, last)
            return last
        time.sleep(0.2)
    raise RuntimeError(f"没有找到产品信息操作入口：{labels} seen={'|'.join(last.get('seen', [])[:20])}")


def _click_dropdown_item(page: Any, labels: list[str], *, exact: bool = True, timeout: float = 8.0) -> dict[str, Any]:
    click_text_scoped = BASE.get("_click_text_scoped")
    if not callable(click_text_scoped):
        raise RuntimeError("缺少下拉菜单点击函数，无法操作产品信息图片")
    return click_text_scoped(page, labels, ".ant-dropdown,.ant-popover,.ant-modal,[role='menu']", exact=exact, timeout=timeout)


def _try_click_open_dropdown_item(page: Any, labels: list[str], *, exact: bool = True) -> dict[str, Any] | None:
    click_text_scoped = BASE.get("_click_text_scoped")
    if not callable(click_text_scoped):
        return None
    try:
        return click_text_scoped(page, labels, ".ant-dropdown,.ant-popover,.ant-modal,[role='menu']", exact=exact, timeout=1.2)
    except Exception:
        return None


def _product_info_image_state(page: Any) -> dict[str, Any]:
    state = page.evaluate(PRODUCT_INFO_IMAGE_STATE_JS)
    return state if isinstance(state, dict) else {"ok": False, "imageCount": 0, "selectedCount": None}


def _state_image_count(state: dict[str, Any]) -> int:
    selected = state.get("selectedCount")
    if selected is not None:
        try:
            return int(selected)
        except Exception:
            pass
    try:
        return int(state.get("imageCount") or 0)
    except Exception:
        return 0


def _wait_product_info_image_count(page: Any, *, target_max: int | None = None, minimum: int | None = None, timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = _product_info_image_state(page)
        count = _state_image_count(last)
        if target_max is not None and count <= target_max:
            return last
        if minimum is not None and count >= minimum:
            return last
        time.sleep(0.35)
    expected = f"<={target_max}" if target_max is not None else f">={minimum}"
    raise RuntimeError(f"等待产品信息图片数量超时：expected {expected}, last={last}")


def _clear_product_info_images(page: Any) -> dict[str, Any]:
    before = _product_info_image_state(page)
    existing_confirm = page.evaluate(PRODUCT_INFO_CONFIRM_IF_ANY_JS)
    if isinstance(existing_confirm, dict) and existing_confirm.get("ok"):
        after = _wait_product_info_image_count(page, target_max=0, timeout=25)
        payload = {"ok": True, "before": before, "menuClick": None, "confirm": existing_confirm, "after": after}
        _save_json("product-info-clear-images", payload)
        _log("OK", "已清空产品信息图片", before=_state_image_count(before), after=_state_image_count(after))
        return payload
    menu_click = _try_click_open_dropdown_item(page, ["\u6e05\u7a7a\u56fe\u7247"], exact=True)
    if menu_click is None:
        _click_product_info_action(page, ["\u7f16\u8f91\u56fe\u7247"], exact=False, timeout=12)
        time.sleep(0.2)
        menu_click = _click_dropdown_item(page, ["\u6e05\u7a7a\u56fe\u7247"], exact=True, timeout=10)
    time.sleep(0.2)
    confirm = page.evaluate(PRODUCT_INFO_CONFIRM_IF_ANY_JS)
    after = _wait_product_info_image_count(page, target_max=0, timeout=25)
    payload = {"ok": True, "before": before, "menuClick": menu_click, "confirm": confirm, "after": after}
    _save_json("product-info-clear-images", payload)
    _log("OK", "已清空产品信息图片", before=_state_image_count(before), after=_state_image_count(after))
    return payload


def _upload_product_info_local_images(page: Any, files: list[str]) -> dict[str, Any]:
    _click_product_info_action(page, ["\u9009\u62e9\u56fe\u7247"], exact=False, timeout=12)
    time.sleep(0.2)
    local_point = page.evaluate(
        BASE.get("FIND_VISIBLE_TEXT_POINT_SCOPED_JS"),
        {"labels": ["\u672c\u5730\u56fe\u7247", "\u672c\u5730\u4e0a\u4f20"], "exact": True, "selector": ".ant-dropdown"},
    )
    if not isinstance(local_point, dict) or not local_point.get("ok"):
        local_point = page.evaluate(
            BASE.get("FIND_VISIBLE_TEXT_POINT_SCOPED_JS"),
            {"labels": ["\u672c\u5730\u56fe\u7247", "\u672c\u5730\u4e0a\u4f20"], "exact": False, "selector": ".ant-dropdown"},
        )
    if not isinstance(local_point, dict) or not local_point.get("ok"):
        raise RuntimeError(f"没有找到产品信息本地图片入口：seen={'|'.join((local_point or {}).get('seen', [])[:20])}")

    try:
        with page.expect_file_chooser(timeout=10000) as chooser_info:
            page.mouse.click(local_point["x"], local_point["y"])
        chooser = chooser_info.value
        if not chooser.is_multiple() and len(files) > 1:
            raise RuntimeError("产品信息本地图片上传控件不是多选控件，无法一次上传多张图片")
        chooser.set_files(files)
    except Exception as exc:
        fallback = BASE.get("_set_local_upload_files")
        if not callable(fallback):
            raise
        _log("WARN", "产品信息本地图片 file chooser 未捕获，改用 input fallback", error=_safe_error_text(exc))
        page.mouse.click(local_point["x"], local_point["y"])
        time.sleep(0.25)
        fallback(page, files)

    expected = min(len(files), 10)
    after = _wait_product_info_image_count(page, minimum=expected, timeout=90)
    payload = {"ok": True, "count": len(files), "files": files, "after": after}
    _save_json("product-info-upload-local-images", payload)
    _log("OK", "已上传产品信息本地图片", count=len(files), selected=_state_image_count(after))
    return payload


def _replace_product_info_images_from_folder(robot: Any, folder: Path) -> dict[str, Any]:
    page = getattr(robot, "page", None)
    if page is None:
        raise RuntimeError("缺少当前编辑页，无法清空并上传产品信息图片")
    files = _uploadable_product_info_image_files(folder)
    clear = _clear_product_info_images(page)
    upload = _upload_product_info_local_images(page, files)
    payload = {"ok": True, "folder": str(folder), "files": files, "clear": clear, "upload": upload}
    _save_json("product-info-replace-images", payload)
    return payload


PRODUCT_DESC_EDITOR_DETECT_RELAXED_JS = r"""
() => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function visible(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'
      && r.bottom>=0&&r.right>=0&&r.top<=innerHeight&&r.left<=innerWidth;
  }
  const wraps=[...document.querySelectorAll('.ant-modal-wrap.full-modal__dxm,.ant-modal-wrap,.ant-modal,[role="dialog"]')].filter(visible);
  return wraps.some(wrap => {
    const txt=clean(wrap.innerText||wrap.textContent||'');
    if(wrap.matches('.full-modal__dxm') && (/使用中模块|添加模块|批量操作|产品描述|Temu产品描述/.test(txt) || wrap.querySelector('.using-modules,.smt-content-center'))) return true;
    return /使用中模块|添加模块|批量操作|清空图片模块|清空文字模块|Temu产品描述/.test(txt) && !!wrap.querySelector('button,.using-modules,.smt-content-center');
  });
}
"""

PRODUCT_DESC_OPEN_EDITOR_CLICK_JS = r"""
async () => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function visible(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'
      && r.bottom>=0&&r.right>=0&&r.top<=innerHeight&&r.left<=innerWidth;
  }
  function hover(el){
    if(!el) return;
    const r=el.getBoundingClientRect();
    const init={bubbles:true,cancelable:true,view:window,clientX:r.x+r.width/2,clientY:r.y+r.height/2};
    for(const type of ['mouseenter','mouseover','mousemove']) el.dispatchEvent(new MouseEvent(type, init));
  }
  function clickElement(el){
    if(!el) return false;
    el.scrollIntoView({block:'center', inline:'center'});
    hover(el);
    const r=el.getBoundingClientRect();
    return {x:r.x+r.width/2, y:r.y+r.height/2};
  }
  function editorOpen(){
    const wraps=[...document.querySelectorAll('.ant-modal-wrap.full-modal__dxm,.ant-modal-wrap,.ant-modal,[role="dialog"]')].filter(visible);
    return wraps.some(wrap => {
      const txt=clean(wrap.innerText||wrap.textContent||'');
      return (wrap.matches('.full-modal__dxm') || /使用中模块|添加模块|批量操作|Temu产品描述/.test(txt))
        && !!wrap.querySelector('button,.using-modules,.smt-content-center');
    });
  }
  if(editorOpen()) return {ok:true, alreadyOpen:true, target:'editor-open'};
  const box=document.querySelector('#wirelessDescBox');
  if(box){
    box.scrollIntoView({block:'center', inline:'center'});
    hover(box);
    await new Promise(resolve => setTimeout(resolve, 120));
  }
  const selectors=[
    '#baiduStatisticsSmtNewEditorEditClickNum button',
    '#baiduStatisticsSmtNewEditorEditClickNum',
    '.wireless-description-shadow button',
    '.wireless-description-shadow',
    '#wirelessDescBox button',
    '#wirelessDescBox [role="button"]',
    '#wirelessDescBox a'
  ];
  const candidates=[];
  for(const selector of selectors){
    const el=document.querySelector(selector);
    if(el && visible(el)) candidates.push({el, target:selector, score:0});
  }
  const scopes=[box, box?.parentElement, document].filter(Boolean);
  for(const scope of scopes){
    const nodes=[...scope.querySelectorAll('button,a,span,div,[role="button"],[class*="edit"],[id*="Edit"]')];
    for(const el of nodes){
      if(!visible(el)) continue;
      const txt=clean(el.innerText||el.textContent||el.getAttribute('title')||el.getAttribute('aria-label')||el.id||el.className||'');
      if(!txt) continue;
      if(/编辑描述|编辑|edit/i.test(txt)){
        const tagScore=['BUTTON','A'].includes(el.tagName) ? 0 : 1;
        const textScore=/编辑描述/.test(txt) ? 0 : 1;
        candidates.push({el, target:txt.slice(0,80), score:tagScore+textScore});
      }
    }
  }
  candidates.sort((a,b)=>a.score-b.score);
  const best=candidates[0];
  if(best){
    const point=clickElement(best.el);
    if(point) return {ok:true, target:best.target, x:point.x, y:point.y};
  }
  if(box && visible(box)){
    const r=box.getBoundingClientRect();
    const x=r.x+r.width/2, y=r.y+r.height/2;
    return {ok:true, target:'wirelessDescBox-center', x, y};
  }
  return {ok:false, target:'', seen: box ? 'found #wirelessDescBox but no clickable editor button' : '找不到 #wirelessDescBox'};
}
"""


PRODUCT_DESC_HOVER_BOX_POINT_JS = r"""
() => {
  const box = document.querySelector('#wirelessDescBox');
  if (!box) return {ok:false, error:'missing #wirelessDescBox'};
  box.scrollIntoView({block:'center', inline:'center'});
  const r = box.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return {ok:false, error:'hidden #wirelessDescBox'};
  return {ok:true, x:r.x + r.width / 2, y:r.y + Math.min(r.height / 2, 180)};
}
"""


_base_open_product_description_editor = BASE.get("_open_product_description_editor")
_base_is_description_editor = BASE.get("_is_description_editor")


def _is_product_description_editor_open_resilient(page: Any) -> bool:
    try:
        return bool(page.evaluate(PRODUCT_DESC_EDITOR_DETECT_RELAXED_JS))
    except Exception:
        if callable(_base_is_description_editor):
            try:
                return bool(_base_is_description_editor(page))
            except Exception:
                return False
        return False


def _open_product_description_editor_resilient(page: Any) -> None:
    if _is_product_description_editor_open_resilient(page):
        _log("OK", "已在产品描述编辑器")
        return
    last: dict[str, Any] = {}
    for attempt in range(1, 4):
        try:
            hover = page.evaluate(PRODUCT_DESC_HOVER_BOX_POINT_JS)
            if isinstance(hover, dict) and hover.get("ok"):
                page.mouse.move(float(hover["x"]), float(hover["y"]))
                time.sleep(0.12)
        except Exception:
            pass
        try:
            result = page.evaluate(PRODUCT_DESC_OPEN_EDITOR_CLICK_JS)
            last = result if isinstance(result, dict) else {"raw": result}
        except Exception as exc:
            last = {"ok": False, "error": _safe_error_text(exc)}
        if last.get("ok") and not last.get("alreadyOpen") and last.get("x") is not None and last.get("y") is not None:
            try:
                page.mouse.click(float(last["x"]), float(last["y"]))
            except Exception as exc:
                last["clickError"] = _safe_error_text(exc)
        for _ in range(10):
            time.sleep(0.25)
            if _is_product_description_editor_open_resilient(page):
                _log("OK", "已打开产品描述编辑器", attempt=attempt, target=last.get("target"))
                return
        _log("WARN", "已点击编辑描述但未检测到编辑器，重试", attempt=attempt, target=last.get("target"), seen=last.get("seen") or last.get("error") or "")
    if callable(_base_open_product_description_editor):
        try:
            _base_open_product_description_editor(page)
            if _is_product_description_editor_open_resilient(page):
                return
        except Exception as exc:
            last = {"ok": False, "error": _safe_error_text(exc)}
    raise RuntimeError(
        "未能自动打开产品描述编辑器。请手动点击一次“产品描述 > 编辑描述”，进入编辑器后重新运行；"
        f"last={last}"
    )


BASE["_open_product_description_editor"] = _open_product_description_editor_resilient
BASE["_is_description_editor"] = _is_product_description_editor_open_resilient


def _product_description_editor_state(page: Any) -> dict[str, Any]:
    reader = BASE.get("_product_description_editor_state")
    if callable(reader):
        state = reader(page)
    else:
        state = page.evaluate(BASE.get("PRODUCT_DESC_ACTIVE_EDITOR_STATE_JS"))
    return state if isinstance(state, dict) else {"ok": False, "centerImageCount": 0, "moduleCount": 0}


def _product_description_image_count(state: dict[str, Any]) -> int:
    using_text = str(state.get("usingText") or "")
    title_text = str(state.get("titleText") or "")
    module_text = f"{title_text} {using_text}"
    module_count_known = "moduleCount" in state or "使用中模块" in module_text
    try:
        module_count = int(state.get("moduleCount") or 0)
    except Exception:
        module_count = 0
    if module_count_known and module_count <= 0:
        if "(0)" in module_text or "（0）" in module_text or "暂无使用中的模块" in module_text or "暂无使用" in module_text:
            return 0
    for key in ("centerImageCount", "imageCount", "visibleImageCount"):
        try:
            value = int(state.get(key) or 0)
        except Exception:
            value = 0
        if value:
            return value
    return 0


def _wait_product_description_image_count(page: Any, *, target_max: int | None = None, minimum: int | None = None, timeout: float = 45.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = _product_description_editor_state(page)
        count = _product_description_image_count(last)
        if target_max is not None and count <= target_max:
            return last
        if minimum is not None and count >= minimum:
            return last
        time.sleep(0.35)
    expected = f"<={target_max}" if target_max is not None else f">={minimum}"
    raise RuntimeError(f"等待产品描述图片模块数量超时：expected {expected}, last={last}")


def _click_product_description_open_menu_item(page: Any, labels: list[str], *, exact: bool = True, timeout: float = 8.0, click: bool = True) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] = {}
    while time.time() < deadline:
        result = page.evaluate(PRODUCT_DESC_CLICK_MENU_ITEM_JS, {"labels": labels, "exact": exact, "click": False})
        last = result if isinstance(result, dict) else {}
        if last.get("ok"):
            if click and last.get("x") is not None and last.get("y") is not None:
                page.mouse.click(float(last["x"]), float(last["y"]))
                last["clicked"] = True
                time.sleep(0.12)
            return last
        time.sleep(0.2)
    raise RuntimeError(f"没有找到产品描述菜单项：{labels} seen={'|'.join(last.get('seen', [])[:20])}")


def _wait_product_description_editor_closed(page: Any, *, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _is_product_description_editor_open_resilient(page):
            return True
        time.sleep(0.2)
    return False


def _clear_product_description_image_modules(page: Any) -> dict[str, Any]:
    before = _product_description_editor_state(page)
    before_count = _product_description_image_count(before)
    if before_count <= 0:
        payload = {"ok": True, "skipped": True, "reason": "no_description_images", "before": before, "after": before}
        _save_json("product-description-clear-image-modules", payload)
        _log("INFO", "产品描述没有图片模块，跳过清空，直接上传")
        return payload

    delete_result = page.evaluate(PRODUCT_DESC_DELETE_IMAGE_MODULES_JS)
    if not isinstance(delete_result, dict) or not delete_result.get("ok"):
        raise RuntimeError(f"清空产品描述图片模块失败：{delete_result}")
    after = _wait_product_description_image_count(page, target_max=0, timeout=45)
    payload = {
        "ok": True,
        "before": before,
        "delete": delete_result,
        "after": after,
    }
    _save_json("product-description-clear-image-modules", payload)
    _log("OK", "已清空产品描述图片模块", before=before_count, after=_product_description_image_count(after))
    return payload


def _upload_product_description_local_images(page: Any, files: list[str]) -> dict[str, Any]:
    click_text_scoped = BASE.get("_click_text_scoped")
    if not callable(click_text_scoped):
        raise RuntimeError("缺少文本点击函数，无法上传产品描述图片")

    batch_label = BASE.get("TEXT_BATCH_OPERATION") or "\u6279\u91cf\u64cd\u4f5c"
    bulk_label = BASE.get("TEXT_BULK_UPLOAD") or "\u6279\u91cf\u4f20\u56fe"
    choose_label = BASE.get("TEXT_CHOOSE_IMAGE") or "\u9009\u62e9\u56fe\u7247"
    local_label = BASE.get("TEXT_LOCAL_UPLOAD") or "\u672c\u5730\u4e0a\u4f20"
    confirm_label = BASE.get("TEXT_CONFIRM") or "\u786e\u5b9a"
    save_label = BASE.get("TEXT_SAVE") or "\u4fdd\u5b58"

    click_text_scoped(page, [batch_label], ".ant-modal-wrap.full-modal__dxm", exact=False, timeout=10)
    time.sleep(0.2)
    _click_product_description_open_menu_item(page, [bulk_label], exact=True, timeout=8)
    time.sleep(0.3)
    click_text_scoped(page, [choose_label], ".batch-smt-image", exact=False, timeout=15)
    time.sleep(0.2)

    local_point = page.evaluate(
        BASE.get("FIND_VISIBLE_TEXT_POINT_SCOPED_JS"),
        {"labels": [local_label, "\u672c\u5730\u56fe\u7247"], "exact": False, "selector": ".ant-dropdown"},
    )
    if not isinstance(local_point, dict) or not local_point.get("ok"):
        local_point = page.evaluate(PRODUCT_DESC_CLICK_MENU_ITEM_JS, {"labels": [local_label, "\u672c\u5730\u56fe\u7247"], "exact": False, "click": False})
    if not isinstance(local_point, dict) or not local_point.get("ok"):
        raise RuntimeError(f"没有找到产品描述本地上传入口；seen={'|'.join((local_point or {}).get('seen', [])[:20])}")

    try:
        with page.expect_file_chooser(timeout=10000) as chooser_info:
            page.mouse.click(local_point["x"], local_point["y"])
        chooser = chooser_info.value
        if not chooser.is_multiple() and len(files) > 1:
            raise RuntimeError("产品描述批量传图的本地上传控件不是多选控件，无法一次上传多张图片")
        chooser.set_files(files)
    except Exception as exc:
        fallback = BASE.get("_set_local_upload_files")
        if not callable(fallback):
            raise
        _log("WARN", "产品描述本地上传 file chooser 未捕获，改用 input fallback", error=_safe_error_text(exc))
        page.mouse.click(local_point["x"], local_point["y"])
        time.sleep(0.25)
        fallback(page, files)

    wait_batch = BASE.get("_wait_for_product_description_batch_upload")
    if callable(wait_batch):
        batch_state = wait_batch(page, len(files), 75)
    else:
        batch_state = {"open": True, "uploadedCount": len(files)}
    _log("OK", "产品描述批量传图弹窗已载入图片", uploaded=batch_state.get("uploadedCount"), count=len(files))

    click_text_scoped(page, [confirm_label], ".batch-smt-image", exact=True, timeout=15)
    wait_modules = BASE.get("_wait_for_product_description_modules")
    if callable(wait_modules):
        module_state = wait_modules(page, len(files), 45)
    else:
        module_state = _wait_product_description_image_count(page, minimum=len(files), timeout=45)
    _log("OK", "当前产品描述编辑器已生成图片模块", modules=module_state.get("moduleCount"), images=_product_description_image_count(module_state))

    click_text_scoped(page, [save_label], ".ant-modal-wrap.full-modal__dxm", exact=True, timeout=20)
    if not _wait_product_description_editor_closed(page, timeout=5):
        _log("WARN", "产品描述保存后编辑器仍未关闭，继续后续流程")
    payload = {"ok": True, "files": files, "count": len(files), "batch": batch_state, "modules": module_state}
    _save_json("product-description-upload-local-images", payload)
    _log("OK", "已保存产品描述本地图片", count=len(files))
    return payload


_base_fill_product_description_images_v2 = BASE.get("fill_product_description_images_v2")
_base_fill_product_description_images = BASE.get("fill_product_description_images")


def fill_product_description_images_replace(self: Any, folder_text: str = "") -> None:
    ensure_connected = getattr(self, "ensure_connected", None)
    if callable(ensure_connected):
        ensure_connected()
    if not hasattr(self, "page") or getattr(self, "page", None) is None:
        bind = getattr(self, "bind_edit_page", None)
        if callable(bind):
            bind()
    page = getattr(self, "page", None)
    if page is None:
        raise RuntimeError("缺少当前编辑页，无法处理产品描述图片")

    resolver = BASE.get("_resolve_image_files_v2") or BASE.get("_resolve_image_files")
    if not callable(resolver):
        raise RuntimeError("缺少图片文件夹解析函数，无法处理产品描述图片")
    files = resolver(folder_text)
    _log("INFO", "开始产品描述图片清空并重新上传", count=len(files), folder=str(Path(files[0]).parent if files else folder_text))

    opener = BASE.get("_open_product_description_editor")
    if not callable(opener):
        raise RuntimeError("缺少产品描述编辑器打开函数")
    opener(page)

    before = _product_description_editor_state(page)
    clear = _clear_product_description_image_modules(page)
    upload = _upload_product_description_local_images(page, files)
    payload = {"ok": True, "before": before, "clear": clear, "upload": upload, "files": files}
    _save_json("product-description-replace-images", payload)


BASE["fill_product_description_images_v2"] = fill_product_description_images_replace
BASE["fill_product_description_images"] = fill_product_description_images_replace


_base_download_product_images = BASE["LEGACY"]["DxmTemuRobot"].download_product_images


def download_product_images_with_postprocess(self: Any, folder_text: str = "") -> Any:
    result = _base_download_product_images(self, folder_text)
    config = _load_pipeline_config()
    image_config = _normalize_image_postprocess_config(config.get("imagePostprocess"))
    folder = _download_result_folder(result, folder_text)
    if not image_config.get("enabled"):
        _log("INFO", "图片下载后处理已关闭，跳过 800x800 压缩", folder=folder_text)
        _replace_product_info_images_from_folder(self, folder)
        return result
    _log(
        "INFO",
        "开始图片下载后处理：1:1 方图 800x800",
        folder=str(folder),
        compressorPath=image_config.get("compressorPath"),
        mode=image_config.get("mode"),
    )
    _postprocess_downloaded_product_images(folder, image_config)
    _replace_product_info_images_from_folder(self, folder)
    return result


BASE["LEGACY"]["DxmTemuRobot"].download_product_images = download_product_images_with_postprocess


_base_find_open_edit_page_for_record = BASE.get("_find_open_edit_page_for_record")
_base_publish_current_edit_page = BASE.get("_publish_current_edit_page")
_base_load_edited_pages_state = BASE.get("_load_edited_pages_state")
_base_save_edited_pages_state = BASE.get("_save_edited_pages_state")


def _publish_progress_payload(records: list[dict[str, Any]], results: list[dict[str, Any]], skipped_count: int) -> dict[str, Any]:
    return {
        "ok": skipped_count == 0,
        "count": len(records),
        "published": sum(1 for item in results if item.get("ok") and not item.get("skipped")),
        "skipped": skipped_count,
        "results": results,
    }


def _mark_publish_skipped(record: dict[str, Any], index: int, error: str) -> dict[str, Any]:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    record["publishStatus"] = "skipped"
    record["publishError"] = error
    record["skippedAt"] = now
    return {
        "ok": False,
        "skipped": True,
        "item": record.get("item", index),
        "url": record.get("url"),
        "editId": record.get("editId"),
        "error": error,
        "skippedAt": now,
    }


def _publish_recorded_edited_pages_skip_failures(robot: Any, config: dict[str, Any]) -> None:
    _clear_stop_request()
    _stop_requested_as_runtime("发布已编辑页")
    if not callable(_base_load_edited_pages_state):
        raise RuntimeError("缺少已编辑页读取函数，无法发布")
    if not callable(_base_save_edited_pages_state):
        raise RuntimeError("缺少已编辑页保存函数，无法发布")
    if not callable(_base_find_open_edit_page_for_record):
        raise RuntimeError("缺少编辑页查找函数，无法发布")
    if not callable(_base_publish_current_edit_page):
        raise RuntimeError("缺少单页发布函数，无法发布")

    records = _base_load_edited_pages_state()
    if not records:
        raise RuntimeError("没有已编辑待发布页记录；请先点“开始自动流程”完成编辑")

    robot.ensure_connected()
    results: list[dict[str, Any]] = []
    skipped_count = 0
    _log("INFO", "开始确认发布已编辑页（失败自动跳过）", count=len(records))

    for index, record in enumerate(records, start=1):
        _stop_requested_as_runtime(f"发布第 {index}/{len(records)} 个商品前")
        status = str(record.get("publishStatus") or "").lower()
        if status == "published":
            result = {
                "ok": True,
                "skipped": True,
                "reason": "already_published",
                "item": record.get("item", index),
                "url": record.get("url"),
                "editId": record.get("editId"),
            }
            results.append(result)
            _log("INFO", "已跳过之前发布成功的编辑页", item=result.get("item"), url=result.get("url"))
            continue

        page = _base_find_open_edit_page_for_record(robot, record)
        if page is None:
            error = f"已编辑页已关闭或未打开，无法发布：item={record.get('item')} url={record.get('url')}"
            results.append(_mark_publish_skipped(record, index, error))
            skipped_count += 1
            _base_save_edited_pages_state(records)
            _save_json("publish-edited-pages-progress", _publish_progress_payload(records, results, skipped_count))
            _notify_task_error("确认发布已编辑页：单商品发布失败已跳过", RuntimeError(error), config=config, robot=robot)
            _log("WARN", "发布失败，已跳过当前商品", item=record.get("item", index), error=error)
            continue

        try:
            result = _base_publish_current_edit_page(page, record)
            if not isinstance(result, dict):
                result = {"ok": True}
        except Exception as exc:
            _stop_requested_as_runtime(f"发布第 {index}/{len(records)} 个商品")
            error = _safe_error_text(exc)
            results.append(_mark_publish_skipped(record, index, error))
            skipped_count += 1
            _base_save_edited_pages_state(records)
            _save_json("publish-edited-pages-progress", _publish_progress_payload(records, results, skipped_count))
            _notify_task_error("确认发布已编辑页：单商品发布失败已跳过", exc, config=config, robot=robot)
            _log("WARN", "发布失败，已跳过当前商品", item=record.get("item", index), url=record.get("url"), error=error)
            continue

        result["item"] = record.get("item", index)
        record["url"] = result.get("url") or record.get("url")
        record["editId"] = result.get("editId") or record.get("editId")
        record["publishStatus"] = "published"
        record["publishedAt"] = result.get("publishedAt") or time.strftime("%Y-%m-%d %H:%M:%S")
        record["publishCloseOk"] = bool((result.get("close") or {}).get("ok"))
        results.append(result)
        _base_save_edited_pages_state(records)
        _save_json("publish-edited-pages-progress", _publish_progress_payload(records, results, skipped_count))
        time.sleep(1.2)

    payload = _publish_progress_payload(records, results, skipped_count)
    _save_json("publish-edited-pages-run", payload)
    if skipped_count:
        _log("WARN", "已完成已编辑页确认发布，部分商品发布失败已跳过", count=len(results), skipped=skipped_count)
    else:
        _log("OK", "已完成已编辑页确认发布", count=len(results))


_base_show_pipeline_control_panel = BASE.get("_show_pipeline_control_panel")
_base_run_pipeline_step_with_retry_for_stop = BASE.get("_run_pipeline_step_with_retry")
_base_run_limited_full_pipeline_for_stop = BASE.get("_run_limited_full_pipeline")
_base_run_full_pipeline_for_stop = BASE.get("_run_full_pipeline")
_base_run_full_pipeline_with_open_action_for_stop = BASE.get("_run_full_pipeline_with_open_action")
_base_manual_menu_for_stop = BASE.get("_manual_menu")
_base_select_warehouse_names_playwright = BASE.get("_select_warehouse_names_playwright")


def _warehouse_selection_error(error_text: str) -> bool:
    return any(
        token in error_text
        for token in (
            "仓库候选",
            "仓库未全部选中",
            "仓库单击后未确认全部选中",
            "仓库最终校验失败",
            "模板外仓库",
            "未确认全部选中",
            "没有找到仓库",
            "仓库下拉框",
        )
    )


def _read_visible_warehouse_options(page: Any, failed_targets: list[str]) -> list[str]:
    options: list[str] = []
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    time.sleep(0.15)
    opener = BASE.get("_open_warehouse_dropdown")
    clearer = BASE.get("_clear_warehouse_search")
    try:
        if callable(opener):
            opener(page)
        if callable(clearer):
            clearer(page)
        time.sleep(0.35)
        visible = page.evaluate(LIST_VISIBLE_WAREHOUSE_OPTIONS_JS)
        if isinstance(visible, list):
            options.extend(str(item) for item in visible)
    except Exception as exc:
        _log("WARN", "仓库自检读取可见候选失败", error=_safe_error_text(exc))
    state_reader = BASE.get("_warehouse_option_state")
    if callable(state_reader):
        for target in failed_targets:
            try:
                state = state_reader(page, target)
                if isinstance(state, dict) and isinstance(state.get("seen"), list):
                    options.extend(str(item) for item in state["seen"])
            except Exception:
                continue
    return _dedupe_warehouse_names(options)


def _sync_warehouse_selection_to_template(page: Any, targets: list[str]) -> dict[str, Any]:
    target_names = _dedupe_warehouse_names(targets)
    if not target_names:
        return {"ok": True, "removed": [], "kept": [], "failed": []}
    opener = BASE.get("_open_warehouse_dropdown")
    try:
        if callable(opener):
            opener(page)
            time.sleep(0.2)
    except Exception as exc:
        _log("WARN", "仓库模板同步前打开下拉失败，将尝试直接清理已选标签", error=_safe_error_text(exc))
    try:
        result = page.evaluate(SYNC_WAREHOUSE_SELECTION_TO_TEMPLATE_JS, {"targets": target_names})
    except Exception as exc:
        _log("WARN", "仓库模板同步失败", error=_safe_error_text(exc), targets="|".join(target_names))
        return {"ok": False, "removed": [], "kept": [], "failed": [], "error": _safe_error_text(exc)}
    if not isinstance(result, dict):
        result = {"ok": False, "removed": [], "kept": [], "failed": [], "raw": result}
    removed = result.get("removed") if isinstance(result.get("removed"), list) else []
    failed = result.get("failed") if isinstance(result.get("failed"), list) else []
    if removed:
        _log("INFO", "仓库模板同步：已取消模板外仓库", removed="|".join(str(item) for item in removed))
        time.sleep(0.5)
    if failed:
        _log("WARN", "仓库模板同步：部分模板外仓库未能自动取消", failed="|".join(str(item) for item in failed))
    return result


def _warehouse_exact_selection_state(page: Any, targets: list[str]) -> dict[str, Any]:
    target_names = _dedupe_warehouse_names(targets)
    try:
        result = page.evaluate(WAREHOUSE_EXACT_SELECTION_STATE_JS, {"targets": target_names})
        if isinstance(result, dict) and result.get("ok"):
            return result
    except Exception as exc:
        _log("WARN", "仓库精确校验 DOM 直读失败，准备打开下拉补充读取", error=_safe_error_text(exc))
    opener = BASE.get("_open_warehouse_dropdown")
    clearer = BASE.get("_clear_warehouse_search")
    try:
        if callable(opener):
            opener(page)
        if callable(clearer):
            clearer(page)
        time.sleep(0.2)
    except Exception as exc:
        _log("WARN", "仓库精确校验前打开下拉失败", error=_safe_error_text(exc))
    try:
        result = page.evaluate(WAREHOUSE_EXACT_SELECTION_STATE_JS, {"targets": target_names})
    except Exception as exc:
        return {"ok": False, "error": _safe_error_text(exc), "states": {}, "selected": [], "missingTargets": target_names, "extraSelected": []}
    return result if isinstance(result, dict) else {"ok": False, "raw": result, "states": {}, "selected": [], "missingTargets": target_names, "extraSelected": []}


def _remove_template_outside_warehouses(page: Any, targets: list[str], *, max_rounds: int = 3) -> dict[str, Any]:
    target_names = _dedupe_warehouse_names(targets)
    last: dict[str, Any] = {}
    for attempt in range(1, max_rounds + 1):
        last = _warehouse_exact_selection_state(page, target_names)
        extra_points = last.get("extraPoints") if isinstance(last.get("extraPoints"), list) else []
        extra_selected = last.get("extraSelected") if isinstance(last.get("extraSelected"), list) else []
        if not extra_selected:
            return last
        clicked: list[str] = []
        for point in extra_points:
            try:
                x = float(point.get("x"))
                y = float(point.get("y"))
                page.mouse.click(x, y)
                clicked.append(str(point.get("text") or ""))
                time.sleep(0.18)
            except Exception as exc:
                _log("WARN", "仓库模板外选项真实点击取消失败", value=point.get("text") if isinstance(point, dict) else "", error=_safe_error_text(exc))
        _log("INFO", "仓库精确同步：已尝试取消模板外仓库", attempt=attempt, extra="|".join(str(item) for item in extra_selected), clicked="|".join(item for item in clicked if item))
        time.sleep(0.25)
    return _warehouse_exact_selection_state(page, target_names)


def _assert_exact_warehouse_selection(state: dict[str, Any], targets: list[str]) -> None:
    target_names = _dedupe_warehouse_names(targets)
    missing = state.get("missingTargets") if isinstance(state.get("missingTargets"), list) else []
    extra = state.get("extraSelected") if isinstance(state.get("extraSelected"), list) else []
    if missing or extra or not state.get("ok"):
        raise RuntimeError(
            "仓库最终校验失败："
            f"目标={ ' | '.join(target_names) }；"
            f"缺少={ ' | '.join(str(item) for item in missing) or '无' }；"
            f"模板外仓库={ ' | '.join(str(item) for item in extra) or '无' }；"
            f"已选={ ' | '.join(str(item) for item in (state.get('selected') or [])) }；"
            f"mainText={state.get('mainText') or ''}"
        )


def _select_warehouse_names_strict(page: Any, targets: list[str]) -> dict[str, Any]:
    target_names = _dedupe_warehouse_names(targets)
    if not target_names:
        raise RuntimeError("仓库配置为空，无法选择仓库")
    state = _warehouse_exact_selection_state(page, target_names)
    if isinstance(state, dict) and state.get("ok"):
        _log(
            "OK",
            "仓库 DOM 校验已通过，跳过重复点选",
            selected="|".join(str(item) for item in (state.get("selected") or [])),
            targets="|".join(target_names),
            mainText=state.get("mainText") or "",
        )
        return state
    _sync_warehouse_selection_to_template(page, target_names)
    state = _remove_template_outside_warehouses(page, target_names)
    if isinstance(state, dict) and state.get("ok"):
        _log(
            "OK",
            "仓库同步后 DOM 校验已通过，跳过重复点选",
            selected="|".join(str(item) for item in (state.get("selected") or [])),
            targets="|".join(target_names),
            mainText=state.get("mainText") or "",
        )
        return state
    _base_select_warehouse_names_playwright(page, target_names)
    state = _remove_template_outside_warehouses(page, target_names)
    missing = state.get("missingTargets") if isinstance(state.get("missingTargets"), list) else []
    if missing:
        _base_select_warehouse_names_playwright(page, target_names)
        state = _remove_template_outside_warehouses(page, target_names)
    _assert_exact_warehouse_selection(state, target_names)
    _log("OK", "仓库最终校验通过", selected="|".join(str(item) for item in (state.get("selected") or [])), targets="|".join(target_names))
    return state


def _show_warehouse_self_check_dialog(
    *,
    failed_targets: list[str],
    options: list[str],
    error_text: str,
) -> dict[str, Any] | None:
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception as exc:
        raise RuntimeError(
            "仓库自检需要弹窗选择，但 Tkinter 不可用；"
            f"当前配置={ '，'.join(failed_targets) }；"
            f"页面候选={ ' | '.join(options[:30]) }；"
            f"弹窗错误={_safe_error_text(exc)}"
        ) from exc

    result: dict[str, Any] | None = None
    window = tk.Tk()
    window.title("仓库自检")
    window.geometry("760x640")
    window.resizable(False, False)
    try:
        window.attributes("-topmost", True)
    except Exception:
        pass

    tk.Label(window, text="当前配置的仓库没有匹配成功，请从页面读取到的仓库中选择。", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
    tk.Label(window, text=f"原配置：{'，'.join(failed_targets) or '空'}", fg="#555", wraplength=680, justify="left").pack(anchor="w", padx=16, pady=(0, 6))
    if error_text:
        tk.Label(window, text=f"失败原因：{error_text[:220]}", fg="#9a3412", wraplength=680, justify="left").pack(anchor="w", padx=16, pady=(0, 8))

    body = tk.Frame(window)
    body.pack(fill="x", padx=16, pady=4)
    scrollbar = tk.Scrollbar(body)
    scrollbar.pack(side="right", fill="y")
    listbox = tk.Listbox(body, selectmode="multiple", height=9, yscrollcommand=scrollbar.set, exportselection=False)
    listbox.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=listbox.yview)

    if options:
        for option in options:
            listbox.insert("end", option)
        if len(options) == 1:
            listbox.selection_set(0)
        else:
            failed_keys = {_warehouse_dedupe_key(item) for item in failed_targets if _warehouse_dedupe_key(item)}
            for index, option in enumerate(options):
                if _warehouse_dedupe_key(option) in failed_keys:
                    listbox.selection_set(index)
    else:
        listbox.insert("end", "没有读取到可见仓库候选，请在下方手动输入")

    manual_var = tk.StringVar(value="")
    template_var = tk.StringVar(value="默认仓库模板")
    save_var = tk.BooleanVar(value=True)
    selected_var = tk.StringVar(value="")

    def selected_names() -> list[str]:
        names = []
        if options:
            for index in listbox.curselection():
                if 0 <= int(index) < len(options):
                    names.append(options[int(index)])
        names.extend(_split_warehouse_names(manual_var.get()))
        return _dedupe_warehouse_names(names)

    def refresh_selected_preview(_event: Any | None = None) -> None:
        names = selected_names()
        selected_var.set("已选择：" + ("，".join(names) if names else "未选择"))

    manual_frame = tk.Frame(window)
    manual_frame.pack(fill="x", padx=16, pady=(8, 2))
    tk.Label(manual_frame, text="手动补充").pack(side="left")
    manual_entry = tk.Entry(manual_frame, textvariable=manual_var, width=64)
    manual_entry.pack(side="left", padx=(8, 0))
    manual_entry.bind("<KeyRelease>", refresh_selected_preview)
    listbox.bind("<<ListboxSelect>>", refresh_selected_preview)

    template_frame = tk.Frame(window)
    template_frame.pack(fill="x", padx=16, pady=(4, 2))
    tk.Checkbutton(template_frame, text="保存为模板并作为以后默认仓库", variable=save_var).pack(side="left")
    tk.Label(template_frame, text="模板名").pack(side="left", padx=(18, 6))
    tk.Entry(template_frame, textvariable=template_var, width=24).pack(side="left")

    status_var = tk.StringVar(value="可多选；多个仓库会按顺序逐个选择。")
    tk.Label(window, textvariable=status_var, fg="#555").pack(anchor="w", padx=16, pady=(4, 0))
    tk.Label(window, textvariable=selected_var, fg="#0b63ce", wraplength=680, justify="left").pack(anchor="w", padx=16, pady=(2, 0))
    refresh_selected_preview()

    def confirm() -> None:
        nonlocal result
        names = selected_names()
        if not names:
            messagebox.showwarning("仓库自检", "请至少选择或输入一个仓库。", parent=window)
            return
        result = {
            "warehouseNames": names,
            "saveTemplate": bool(save_var.get()),
            "templateName": template_var.get().strip() or "默认仓库模板",
        }
        window.destroy()

    def cancel() -> None:
        nonlocal result
        result = None
        window.destroy()

    buttons = tk.Frame(window)
    buttons.pack(side="bottom", fill="x", padx=16, pady=(8, 14))
    tk.Button(buttons, text="取消", width=12, command=cancel).pack(side="right")
    tk.Button(buttons, text="保存配置并继续", width=16, command=confirm).pack(side="right", padx=(0, 8))
    window.protocol("WM_DELETE_WINDOW", cancel)
    window.mainloop()
    return result


def _select_warehouse_names_with_self_check(page: Any, targets: list[str]) -> None:
    target_names = _dedupe_warehouse_names(targets)
    if not callable(_base_select_warehouse_names_playwright):
        raise RuntimeError("缺少仓库选择函数")
    try:
        _select_warehouse_names_strict(page, target_names)
        return
    except Exception as exc:
        error_text = _safe_error_text(exc)
        if not _warehouse_selection_error(error_text):
            raise
        try:
            current_state = _warehouse_exact_selection_state(page, target_names)
            if isinstance(current_state, dict) and current_state.get("ok"):
                _log(
                    "OK",
                    "仓库选择异常后复检已通过，跳过自检弹窗",
                    selected="|".join(str(item) for item in (current_state.get("selected") or [])),
                    targets="|".join(target_names),
                    previousError=error_text,
                )
                return
        except Exception as verify_exc:
            _log("WARN", "仓库选择异常后复检失败，继续弹出自检窗口", error=_safe_error_text(verify_exc), previousError=error_text)
        options = _read_visible_warehouse_options(page, target_names)
        _log("WARN", "仓库自检触发", configured="|".join(target_names), options="|".join(options[:20]), error=error_text)
        choice = _show_warehouse_self_check_dialog(failed_targets=target_names, options=options, error_text=error_text)
        if not choice:
            raise RuntimeError(
                f"仓库自检已取消；当前配置={'，'.join(target_names)}；页面候选={' | '.join(options[:30])}"
            ) from exc
        selected_names = _dedupe_warehouse_names(choice.get("warehouseNames") or [])
        if not selected_names:
            raise RuntimeError("仓库自检未选择任何仓库") from exc
        _apply_warehouse_selection_to_runtime(selected_names)
        if choice.get("saveTemplate"):
            _save_warehouse_template_selection(selected_names, template_name=str(choice.get("templateName") or "默认仓库模板"))
        _log("INFO", "仓库自检已回填，继续使用原多仓库选择逻辑", warehouses="|".join(selected_names))
        _select_warehouse_names_strict(page, selected_names)
        return


def _run_stoppable_task(name: str, action: Any, *args: Any, clear: bool = True, **kwargs: Any) -> Any:
    if clear:
        _clear_stop_request()
    config = args[1] if len(args) > 1 and isinstance(args[1], dict) else None
    robot = args[0] if args else None
    try:
        _check_stop(name)
        result = action(*args, **kwargs)
        _notify_task_success(name, config=config)
        return result
    except StopRequested as exc:
        _log("WARN", "已停止当前任务", task=name)
        _notify_task_stopped(name, config=config)
        raise RuntimeError(str(exc) or "已停止当前任务") from None
    except Exception as exc:
        _notify_task_error(name, exc, config=config, robot=robot)
        raise


def _frontend_required_error_texts_for_gate(page: Any) -> list[str]:
    if page is None:
        return []
    try:
        frontend_errors = _frontend_required_errors(page)
    except Exception as exc:
        _log("WARN", "图片下载前复检读取前台错误失败", error=_safe_error_text(exc))
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in frontend_errors:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        text = str(item.get("text") or "").strip()
        item_text = str(item.get("itemText") or "").strip()
        if _is_optional_basic_attr_label(label):
            continue
        if label and text:
            value = f"{label}: {text}"
        else:
            value = text or item_text
        value = " ".join(str(value or "").split())
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _ensure_info_complete_before_image_download(robot: Any) -> None:
    _log("INFO", "图片下载前复检：执行基本信息和产品信息补全")
    checks = (
        ("scan_basic_attrs", "扫描基本信息商品属性"),
        ("fill_basic_required_attrs", "AI补全基本信息红星必填商品属性"),
        ("fill_product_info_required_fields", "补全产品信息红星必填字段"),
    )
    for method_name, step_name in checks:
        _check_stop(f"图片下载前复检 {step_name}")
        method = getattr(robot, method_name, None)
        if not callable(method):
            _log("WARN", "图片下载前复检跳过缺失方法", method=method_name, step=step_name)
            continue
        result = method()
        _validate_required_info_result(step_name, result)
    _validate_frontend_required_state(robot, "AI补全基本信息红星必填商品属性")
    page = getattr(robot, "page", None)
    frontend_errors = _frontend_required_error_texts_for_gate(page)
    if frontend_errors:
        raise RuntimeError("图片下载前信息仍未填全：" + " | ".join(frontend_errors[:8]))
    _log("OK", "图片下载前复检通过：允许进入图片下载")


def _run_pipeline_step_with_retry_stoppable(robot: Any, index: int, total: int, name: str, action: Any) -> Any:
    last_error = ""
    max_attempts = int(BASE.get("MAX_MODULE_RETRIES") or 1)
    for attempt in range(1, max_attempts + 1):
        _check_stop(f"步骤 {index}/{total} {name} 开始前")
        try:
            _log("INFO", "自动流程步骤开始", index=index, total=total, step=name, attempt=attempt, maxAttempts=max_attempts)
            if "下载产品信息模块图片" in name:
                _ensure_info_complete_before_image_download(robot)
            value = action()
            _validate_required_info_result(name, value)
            _validate_frontend_required_state(robot, name)
            _check_stop(f"步骤 {index}/{total} {name} 完成后")
            _log("OK", "自动流程步骤完成", index=index, total=total, step=name, attempt=attempt)
            return value
        except StopRequested:
            raise
        except Exception as exc:
            if STOP_EVENT.is_set():
                raise StopRequested(f"已停止当前任务：步骤 {index}/{total} {name}") from exc
            last_error = _safe_error_text(exc)
            if attempt >= max_attempts:
                _log("ERROR", "自动流程步骤失败且达到最大轮询次数", index=index, total=total, step=name, attempts=attempt, error=last_error)
                raise RuntimeError(f"{name} 连续失败 {max_attempts} 次：{last_error}") from exc
            _log("WARN", "自动流程步骤失败，准备恢复后重试", index=index, total=total, step=name, attempt=attempt, nextAttempt=attempt + 1, error=last_error)
            recovery = BASE.get("_recover_after_pipeline_step_failure")
            if callable(recovery):
                recovery(robot, index, name, attempt, last_error)
    raise RuntimeError(f"{name} 连续失败 {max_attempts} 次：{last_error}")


def _base_callable(name: str) -> Any:
    fn = BASE.get(name)
    if not callable(fn):
        raise RuntimeError(f"缺少流程函数：{name}")
    return fn


def _collection_is_exhausted(error_text: str) -> bool:
    return any(
        token in error_text
        for token in (
            "没有未处理商品",
            "没有未处理",
            "采集箱列表没有找到可编辑商品",
        )
    )


def _run_limited_full_pipeline_now_or_wait(robot: Any, config: dict[str, Any]) -> None:
    limit = int(_base_callable("_pipeline_batch_limit")(config))
    auto_publish = bool(config.get("autoPublishAfterEdit", BASE.get("DEFAULT_AUTO_PUBLISH_AFTER_EDIT", False)))
    save_records = _base_save_edited_pages_state or _base_callable("_save_edited_pages_state")
    ensure_source_page = _base_callable("_ensure_collection_source_page")
    close_blank_pages = _base_callable("_close_blank_edit_pages")
    open_from_source = _base_callable("_open_collection_edit_from_source")
    make_record = _base_callable("_edited_page_record")
    publish_current = _base_publish_current_edit_page or _base_callable("_publish_current_edit_page")

    processed_keys: set[Any] = set()
    batch_results: list[dict[str, Any]] = []
    edited_records: list[dict[str, Any]] = []
    save_records([])
    source_page = ensure_source_page(robot)
    close_blank_pages(robot)
    _log("INFO", "开始按数量批量处理", limit=limit, directPublish=auto_publish)

    for item_index in range(1, limit + 1):
        _stop_requested_as_runtime(f"处理第 {item_index}/{limit} 个商品前")
        item_config = dict(config)
        item_config["imageFolderSuffix"] = f"dxm_temu_{time.strftime('%Y%m%d_%H%M%S')}_item{item_index:03d}"
        run_name = ("批量直接发布 " if auto_publish else "批量编辑待确认 ") + f"{item_index}/{limit}"
        _log("INFO", "批量商品开始", item=item_index, total=limit, directPublish=auto_publish)

        def open_action() -> dict[str, Any]:
            nonlocal source_page
            try:
                closed = callable(getattr(source_page, "is_closed", None)) and source_page.is_closed()
                url = str(getattr(source_page, "url", "") or "")
            except Exception:
                closed = True
                url = ""
            if closed or "/web/popTemu/pageList/draft" not in url:
                source_page = ensure_source_page(robot)
            return open_from_source(robot, source_page, processed_keys)

        try:
            payload = _run_full_pipeline_with_open_action_stoppable(robot, item_config, open_action, run_name=run_name)
        except RuntimeError as exc:
            text = _safe_error_text(exc)
            if STOP_EVENT.is_set() or "停止" in text or "已停止" in text:
                raise
            if _collection_is_exhausted(text) and batch_results:
                _log("WARN", "当前采集箱页面可处理商品已用完，提前结束本轮批量", requested=limit, processed=len(batch_results), error=text)
                break
            page = getattr(robot, "page", None)
            url = str(getattr(page, "url", "") or "")
            failed_record = {
                "item": item_index,
                "url": url,
                "editId": _temu_edit_id(url),
                "pipelineStatus": "skipped_failed",
                "pipelineError": text,
                "failedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            edited_records.append(failed_record)
            save_records(edited_records)
            batch_results.append({"item": item_index, "record": failed_record, "skipped": True, "error": text})
            _save_json(
                "auto-pipeline-item-skipped-error",
                {"ok": False, "skipped": True, "item": item_index, "total": limit, "record": failed_record, "error": text},
            )
            _log("ERROR", "单个商品自动流程失败，已跳过当前商品并继续下一个", item=item_index, total=limit, error=text, url=url)
            try:
                source_page.bring_to_front()
            except Exception:
                source_page = ensure_source_page(robot)
            time.sleep(0.25)
            continue

        record = make_record(item_index, payload, robot)

        if auto_publish:
            page = getattr(robot, "page", None)
            if page is None and callable(_base_find_open_edit_page_for_record):
                page = _base_find_open_edit_page_for_record(robot, record)
            if page is None:
                error = f"第 {item_index}/{limit} 个商品填写完成，但找不到当前编辑页，无法直接发布"
                record["publishStatus"] = "failed"
                record["publishError"] = error
                record["failedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
                edited_records.append(record)
                save_records(edited_records)
                skipped_publish = {"ok": False, "skipped": True, "error": error}
                batch_results.append({"item": item_index, "record": record, "result": payload, "publish": skipped_publish})
                _save_json(
                    "auto-pipeline-direct-publish-error",
                    {"ok": False, "skipped": True, "item": item_index, "record": record, "error": error},
                )
                _notify_task_error(f"{run_name}：单商品发布失败已跳过", RuntimeError(error), config=item_config, robot=robot)
                _log("ERROR", "单个商品填写完成但直接发布失败，已跳过发布并继续", item=item_index, total=limit, error=error)
                continue
            try:
                publish_result = publish_current(page, record)
                if not isinstance(publish_result, dict):
                    publish_result = {"ok": True}
            except Exception as exc:
                error = _safe_error_text(exc)
                record["publishStatus"] = "failed"
                record["publishError"] = error
                record["failedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
                edited_records.append(record)
                save_records(edited_records)
                skipped_publish = {"ok": False, "skipped": True, "error": error}
                batch_results.append({"item": item_index, "record": record, "result": payload, "publish": skipped_publish})
                _save_json(
                    "auto-pipeline-direct-publish-error",
                    {"ok": False, "skipped": True, "item": item_index, "record": record, "error": error},
                )
                _notify_task_error(f"{run_name}：单商品发布失败已跳过", exc, config=item_config, robot=robot)
                _log(
                    "ERROR",
                    "单个商品填写完成但直接发布失败，已跳过发布并继续",
                    item=item_index,
                    total=limit,
                    error=error,
                )
                continue

            record["url"] = publish_result.get("url") or record.get("url")
            record["editId"] = publish_result.get("editId") or record.get("editId")
            record["publishStatus"] = "published"
            record["publishedAt"] = publish_result.get("publishedAt") or time.strftime("%Y-%m-%d %H:%M:%S")
            record["publishCloseOk"] = bool((publish_result.get("close") or {}).get("ok"))
            edited_records.append(record)
            save_records(edited_records)
            batch_results.append({"item": item_index, "record": record, "result": payload, "publish": publish_result})
            _log("OK", "单个商品填写完成并已直接发布", item=item_index, total=limit, url=record.get("url"))
        else:
            edited_records.append(record)
            save_records(edited_records)
            batch_results.append({"item": item_index, "record": record, "result": payload})
            _log("OK", "批量编辑商品完成，已记录编辑页待确认发布", item=item_index, total=limit, url=record.get("url"), imageFolder=payload.get("imageFolder") if isinstance(payload, dict) else "")

        try:
            source_page.bring_to_front()
        except Exception:
            source_page = ensure_source_page(robot)
        time.sleep(0.25)

    run_payload = {
        "ok": True,
        "directPublish": auto_publish,
        "limit": limit,
        "processed": len(batch_results),
        "records": edited_records,
        "results": batch_results,
    }
    _save_json("auto-pipeline-batch-direct-publish" if auto_publish else "auto-pipeline-batch-edit-wait-publish", run_payload)
    if auto_publish:
        _log("OK", "批量直接发布已完成", limit=limit, processed=len(batch_results))
    else:
        _log("OK", "批量编辑已完成，暂不发布；请人工检查后点“确认发布已编辑页”", limit=limit, processed=len(batch_results))


def _run_limited_full_pipeline_stoppable(robot: Any, config: dict[str, Any]) -> Any:
    return _run_stoppable_task("补全产品信息并开始自动流程", _run_limited_full_pipeline_now_or_wait, robot, config)


def _run_full_pipeline_stoppable(robot: Any, config: dict[str, Any]) -> Any:
    if not callable(_base_run_full_pipeline_for_stop):
        raise RuntimeError("缺少完整自动流程函数")
    return _run_stoppable_task("完整自动流程", _base_run_full_pipeline_for_stop, robot, config, clear=False)


def _run_full_pipeline_with_open_action_stoppable(robot: Any, config: dict[str, Any], open_action: Any, run_name: str = "完整自动流程") -> Any:
    if not callable(_base_run_full_pipeline_with_open_action_for_stop):
        raise RuntimeError("缺少完整自动流程函数")
    return _run_stoppable_task(run_name, _base_run_full_pipeline_with_open_action_for_stop, robot, config, open_action, run_name, clear=False)


def _publish_recorded_edited_pages_stoppable(robot: Any, config: dict[str, Any]) -> Any:
    return _run_stoppable_task("确认发布已编辑页", _publish_recorded_edited_pages_skip_failures, robot, config)


def _manual_menu_stoppable(robot: Any, config: dict[str, Any]) -> Any:
    if not callable(_base_manual_menu_for_stop):
        raise RuntimeError("缺少手动菜单函数")
    return _run_stoppable_task("手动菜单", _base_manual_menu_for_stop, robot, config)

def _load_ai_config_file() -> dict[str, Any]:
    payload = dict(DEFAULT_AI_CONFIG)
    try:
        if LAOZHANG_API_CONFIG_PATH.exists():
            loaded = json.loads(LAOZHANG_API_CONFIG_PATH.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                payload.update(loaded)
    except Exception as exc:
        _log("WARN", "读取 AI 配置失败", error=_safe_error_text(exc))
    for key in ("providerName", "baseUrl", "apiKey", "model"):
        payload[key] = str(payload.get(key) or "").strip()
    try:
        payload["timeoutMs"] = int(payload.get("timeoutMs") or DEFAULT_AI_CONFIG["timeoutMs"])
    except Exception:
        payload["timeoutMs"] = DEFAULT_AI_CONFIG["timeoutMs"]
    return payload


def _save_ai_config_file(config: dict[str, Any]) -> None:
    payload = dict(DEFAULT_AI_CONFIG)
    payload.update(config)
    for key in ("providerName", "baseUrl", "apiKey", "model"):
        payload[key] = str(payload.get(key) or "").strip()
    try:
        payload["timeoutMs"] = int(payload.get("timeoutMs") or DEFAULT_AI_CONFIG["timeoutMs"])
    except Exception:
        payload["timeoutMs"] = DEFAULT_AI_CONFIG["timeoutMs"]
    LAOZHANG_API_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAOZHANG_API_CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _as_int(value: Any, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        number = int(str(value).strip())
    except Exception:
        number = default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _show_unified_settings_window(parent: Any | None = None) -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox

    pipeline = _load_pipeline_config()
    ai = _load_ai_config_file()
    feishu = _normalize_feishu_bot_config(pipeline.get("feishuBot"))
    image_cfg = _normalize_image_postprocess_config(pipeline.get("imagePostprocess"))

    window = tk.Toplevel(parent) if parent is not None else tk.Tk()
    window.title("Dxm Temu 统一配置")
    window.geometry("780x860")
    window.minsize(760, 620)
    window.resizable(True, True)

    vars_map: dict[str, Any] = {
        "providerName": tk.StringVar(value=str(ai.get("providerName") or "")),
        "baseUrl": tk.StringVar(value=str(ai.get("baseUrl") or "")),
        "apiKey": tk.StringVar(value=str(ai.get("apiKey") or "")),
        "model": tk.StringVar(value=str(ai.get("model") or "")),
        "timeoutMs": tk.StringVar(value=str(ai.get("timeoutMs") or DEFAULT_AI_CONFIG["timeoutMs"])),
        "imageBaseDir": tk.StringVar(value=str(pipeline.get("imageBaseDir") or "")),
        "batchLimit": tk.StringVar(value=str(pipeline.get("batchLimit") or "")),
        "warehouseName": tk.StringVar(value=str(pipeline.get("warehouseName") or "")),
        "shippingTemplate": tk.StringVar(value=str(pipeline.get("shippingTemplate") or "")),
        "shippingLeadDays": tk.StringVar(value=str(pipeline.get("shippingLeadDays") or "")),
        "webhookUrl": tk.StringVar(value=str(feishu.get("webhookUrl") or "")),
        "secret": tk.StringVar(value=str(feishu.get("secret") or "")),
        "keyword": tk.StringVar(value=str(feishu.get("keyword") or "店小秘")),
        "targetWidth": tk.StringVar(value=str(image_cfg.get("targetWidth") or 800)),
        "targetHeight": tk.StringVar(value=str(image_cfg.get("targetHeight") or 800)),
        "quality": tk.StringVar(value=str(image_cfg.get("quality") or 88)),
        "maxBytesMb": tk.StringVar(value=str(round(int(image_cfg.get("maxBytes") or 2097152) / 1024 / 1024, 2))),
        "compressorPath": tk.StringVar(value=str(image_cfg.get("compressorPath") or "")),
    }
    bools: dict[str, Any] = {
        "useRunSubfolder": tk.BooleanVar(value=bool(pipeline.get("useRunSubfolder", True))),
        "autoPublishAfterEdit": tk.BooleanVar(value=bool(pipeline.get("autoPublishAfterEdit", False))),
        "feishuEnabled": tk.BooleanVar(value=bool(feishu.get("enabled")) and bool(feishu.get("webhookUrl"))),
        "notifyOnError": tk.BooleanVar(value=bool(feishu.get("notifyOnError", True))),
        "notifyOnStop": tk.BooleanVar(value=bool(feishu.get("notifyOnStop", True))),
        "notifyOnSuccess": tk.BooleanVar(value=bool(feishu.get("notifyOnSuccess", False))),
        "imageEnabled": tk.BooleanVar(value=bool(image_cfg.get("enabled", True))),
    }

    def section(row: int, title: str) -> int:
        tk.Label(window, text=title, font=("Microsoft YaHei UI", 11, "bold")).grid(row=row, column=0, columnspan=4, sticky="w", padx=18, pady=(14, 6))
        return row + 1

    def entry(row: int, label: str, key: str, width: int = 52, show: str | None = None) -> int:
        tk.Label(window, text=label).grid(row=row, column=0, sticky="e", padx=(18, 8), pady=4)
        tk.Entry(window, textvariable=vars_map[key], width=width, show=show or "").grid(row=row, column=1, columnspan=3, sticky="w", pady=4)
        return row + 1

    row = 0
    row = section(row, "AI API")
    row = entry(row, "服务商", "providerName")
    row = entry(row, "Base URL", "baseUrl")
    row = entry(row, "API Key", "apiKey", show="*")
    row = entry(row, "模型", "model")
    row = entry(row, "超时(ms)", "timeoutMs", width=18)

    row = section(row, "飞书机器人")
    tk.Checkbutton(window, text="启用飞书通知（webhook 为空时自动关闭）", variable=bools["feishuEnabled"]).grid(row=row, column=1, columnspan=3, sticky="w", pady=4)
    row += 1
    row = entry(row, "Webhook", "webhookUrl")
    row = entry(row, "签名 Secret", "secret", show="*")
    row = entry(row, "关键词", "keyword", width=18)
    tk.Checkbutton(window, text="错误通知", variable=bools["notifyOnError"]).grid(row=row, column=1, sticky="w", pady=4)
    tk.Checkbutton(window, text="停止通知", variable=bools["notifyOnStop"]).grid(row=row, column=2, sticky="w", pady=4)
    tk.Checkbutton(window, text="成功通知", variable=bools["notifyOnSuccess"]).grid(row=row, column=3, sticky="w", pady=4)
    row += 1

    row = section(row, "流程配置")
    row = entry(row, "图片根目录", "imageBaseDir")

    def browse_image_dir() -> None:
        selected = filedialog.askdirectory(parent=window, initialdir=vars_map["imageBaseDir"].get() or str(APP_DIR))
        if selected:
            vars_map["imageBaseDir"].set(selected)

    tk.Button(window, text="选择", command=browse_image_dir, width=8).grid(row=row - 1, column=3, sticky="e", padx=(0, 18))
    row = entry(row, "批量数量", "batchLimit", width=18)
    tk.Checkbutton(window, text="使用每次运行子目录", variable=bools["useRunSubfolder"]).grid(row=row, column=1, sticky="w", pady=4)
    tk.Checkbutton(window, text="填写完成后直接发布", variable=bools["autoPublishAfterEdit"]).grid(row=row, column=2, columnspan=2, sticky="w", pady=4)
    row += 1
    row = entry(row, "仓库", "warehouseName")
    row = entry(row, "运费模板", "shippingTemplate")
    row = entry(row, "发货天数", "shippingLeadDays", width=18)

    row = section(row, "图片处理")
    tk.Checkbutton(window, text="启用下载后图片处理", variable=bools["imageEnabled"]).grid(row=row, column=1, columnspan=3, sticky="w", pady=4)
    row += 1
    row = entry(row, "目标宽", "targetWidth", width=18)
    row = entry(row, "目标高", "targetHeight", width=18)
    row = entry(row, "质量", "quality", width=18)
    row = entry(row, "最大 MB", "maxBytesMb", width=18)
    row = entry(row, "压缩工具", "compressorPath")

    status_var = tk.StringVar(value="配置只保存在本机，不会上传到其它地方。")
    tk.Label(window, textvariable=status_var, fg="#555").grid(row=row, column=0, columnspan=4, sticky="w", padx=18, pady=(12, 6))
    row += 1

    def collect_pipeline_config() -> dict[str, Any]:
        updated = dict(pipeline)
        updated["imageBaseDir"] = vars_map["imageBaseDir"].get().strip()
        updated["useRunSubfolder"] = bool(bools["useRunSubfolder"].get())
        updated["autoPublishAfterEdit"] = bool(bools["autoPublishAfterEdit"].get())
        updated["batchLimit"] = _as_int(vars_map["batchLimit"].get(), int(pipeline.get("batchLimit") or 1), minimum=1)
        updated["warehouseName"] = vars_map["warehouseName"].get().strip()
        updated["shippingTemplate"] = vars_map["shippingTemplate"].get().strip()
        updated["shippingLeadDays"] = _as_int(vars_map["shippingLeadDays"].get(), int(pipeline.get("shippingLeadDays") or 9), minimum=1)
        max_bytes = int(float(vars_map["maxBytesMb"].get() or "2") * 1024 * 1024)
        updated["imagePostprocess"] = _normalize_image_postprocess_config(
            {
                **image_cfg,
                "enabled": bool(bools["imageEnabled"].get()),
                "targetWidth": _as_int(vars_map["targetWidth"].get(), 800, minimum=1),
                "targetHeight": _as_int(vars_map["targetHeight"].get(), 800, minimum=1),
                "quality": _as_int(vars_map["quality"].get(), 88, minimum=50, maximum=95),
                "maxBytes": max_bytes,
                "compressorPath": vars_map["compressorPath"].get().strip(),
            }
        )
        webhook = vars_map["webhookUrl"].get().strip()
        updated["feishuBot"] = _normalize_feishu_bot_config(
            {
                "enabled": bool(bools["feishuEnabled"].get()) and bool(webhook),
                "webhookUrl": webhook,
                "secret": vars_map["secret"].get().strip(),
                "notifyOnError": bool(bools["notifyOnError"].get()),
                "notifyOnStop": bool(bools["notifyOnStop"].get()),
                "notifyOnSuccess": bool(bools["notifyOnSuccess"].get()),
                "keyword": vars_map["keyword"].get().strip() or "店小秘",
            }
        )
        return updated

    def collect_ai_config() -> dict[str, Any]:
        return {
            "providerName": vars_map["providerName"].get().strip() or DEFAULT_AI_CONFIG["providerName"],
            "baseUrl": vars_map["baseUrl"].get().strip() or DEFAULT_AI_CONFIG["baseUrl"],
            "apiKey": vars_map["apiKey"].get().strip(),
            "model": vars_map["model"].get().strip() or DEFAULT_AI_CONFIG["model"],
            "timeoutMs": _as_int(vars_map["timeoutMs"].get(), DEFAULT_AI_CONFIG["timeoutMs"], minimum=1000),
        }

    def save_all() -> None:
        try:
            _save_ai_config_file(collect_ai_config())
            _save_pipeline_config(collect_pipeline_config())
            status_var.set("已保存统一配置。")
            messagebox.showinfo("统一配置", "配置已保存。", parent=window)
        except Exception as exc:
            status_var.set("保存失败。")
            messagebox.showerror("统一配置", _safe_error_text(exc), parent=window)

    def test_feishu() -> None:
        cfg = collect_pipeline_config()
        if not (cfg.get("feishuBot") or {}).get("webhookUrl"):
            messagebox.showinfo("测试飞书", "Webhook 为空，飞书通知未启用。", parent=window)
            return
        ok = _send_feishu_text("测试通知", "DxmTemuTerminalRobot 飞书机器人配置可用。", level="INFO", config=cfg)
        status_var.set("飞书测试已发送。" if ok else "飞书测试失败，请检查 webhook/secret。")
        messagebox.showinfo("测试飞书", "已发送测试通知。" if ok else "发送失败，请查看日志。", parent=window)

    tk.Frame(window, height=52).grid(row=row, column=0, columnspan=4, sticky="ew")
    button_frame = tk.Frame(window, bd=1, relief="flat")
    button_frame.place(relx=1.0, rely=1.0, anchor="se", x=-18, y=-16)
    tk.Button(button_frame, text="测试飞书", command=test_feishu, width=12).pack(side="right", padx=(8, 0))
    tk.Button(button_frame, text="保存", command=save_all, width=12).pack(side="right", padx=(8, 0))
    tk.Button(button_frame, text="关闭", command=window.destroy, width=12).pack(side="right")
    button_frame.lift()
    window.bind("<Control-s>", lambda _event: save_all())

    if parent is not None:
        window.transient(parent)
        window.grab_set()


def _hide_redundant_ai_api_buttons(widget: Any) -> None:
    target_texts = {"AI/API配置", "AI API配置", "AI配置", "API配置"}

    def visit(node: Any) -> None:
        try:
            text = str(node.cget("text") or "").strip()
        except Exception:
            text = ""
        if text in target_texts:
            for method_name in ("pack_forget", "grid_remove", "place_forget"):
                method = getattr(node, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:
                        pass
            return
        try:
            children = list(node.winfo_children())
        except Exception:
            children = []
        for child in children:
            visit(child)

    visit(widget)


def _capture_run_task_controls(callback: Any, state: dict[str, Any]) -> None:
    seen: set[int] = set()

    def visit(obj: Any) -> bool:
        obj_id = id(obj)
        if obj_id in seen:
            return False
        seen.add(obj_id)
        code = getattr(obj, "__code__", None)
        closure = getattr(obj, "__closure__", None)
        if code is not None and code.co_name == "run_task" and closure:
            cells: dict[str, Any] = {}
            for name, cell in zip(code.co_freevars, closure):
                try:
                    cells[name] = cell.cell_contents
                except ValueError:
                    pass
            if callable(cells.get("set_running")) and isinstance(cells.get("running"), dict):
                state["set_running"] = cells["set_running"]
                state["running"] = cells["running"]
                return True
        if closure:
            for cell in closure:
                try:
                    child = cell.cell_contents
                except ValueError:
                    continue
                if callable(child) and visit(child):
                    return True
        return False

    if callable(callback):
        visit(callback)


def _show_pipeline_control_panel_with_stop_button() -> None:
    if not callable(_base_show_pipeline_control_panel):
        raise RuntimeError("缺少控制台弹窗函数")
    import tkinter as tk

    original_tk = tk.Tk
    original_button = tk.Button
    control_state: dict[str, Any] = {"set_running": None, "running": None, "stop_zero_polls": 0}

    def tracked_button(*args: Any, **kwargs: Any) -> Any:
        _capture_run_task_controls(kwargs.get("command"), control_state)
        return original_button(*args, **kwargs)

    def tk_with_stop_button(*args: Any, **kwargs: Any) -> Any:
        root = original_tk(*args, **kwargs)
        _register_control_root(root)
        try:
            root.protocol("WM_DELETE_WINDOW", lambda: _close_main_window_and_exit(root))
        except Exception as exc:
            _log("WARN", "绑定主窗口关闭退出失败", error=_safe_error_text(exc))

        def add_stop_button() -> None:
            try:
                try:
                    root.protocol("WM_DELETE_WINDOW", lambda: _close_main_window_and_exit(root))
                except Exception:
                    pass
                _hide_redundant_ai_api_buttons(root)
                frame = tk.Frame(root)
                frame.pack(fill="x", padx=16, pady=(0, 10))

                stop_button = original_button(frame, text="停止当前任务", width=14, bg="#d93025", fg="white", activebackground="#b3261e", activeforeground="white")

                def restore_when_stopped() -> None:
                    try:
                        if not bool(stop_button.winfo_exists()):
                            return
                        active_count = len(_active_robots_snapshot())
                        if active_count > 0:
                            control_state["stop_zero_polls"] = 0
                            root.after(800, restore_when_stopped)
                            return
                        control_state["stop_zero_polls"] = int(control_state.get("stop_zero_polls") or 0) + 1
                        if control_state["stop_zero_polls"] < 2:
                            root.after(800, restore_when_stopped)
                            return
                        _clear_stop_request()
                        running_state = control_state.get("running")
                        if isinstance(running_state, dict):
                            running_state["active"] = False
                        set_running = control_state.get("set_running")
                        if callable(set_running):
                            try:
                                set_running(False, "已停止当前任务，可以继续。")
                            except Exception as exc:
                                _log("WARN", "停止后恢复控制面板运行状态失败", error=_safe_error_text(exc))
                        stop_button.configure(text="停止当前任务", state="normal")
                        _log("OK", "停止完成，控制面板已恢复，可继续执行新任务")
                    except Exception as exc:
                        _log("WARN", "停止按钮恢复状态失败", error=_safe_error_text(exc))
                        try:
                            stop_button.configure(text="停止当前任务", state="normal")
                        except Exception:
                            pass

                def stop_clicked() -> None:
                    stop_button.configure(text="停止请求已发送", state="disabled")
                    control_state["stop_zero_polls"] = 0
                    _request_stop_from_gui()
                    root.after(800, restore_when_stopped)

                stop_button.configure(command=stop_clicked)
                stop_button.pack(side="right")
                test_button = original_button(frame, text="测试飞书", width=10)

                def test_feishu_clicked() -> None:
                    ok = _send_feishu_text("测试通知", "DxmTemuTerminalRobot 飞书机器人配置可用。", level="INFO")
                    test_button.configure(text="测试已发送" if ok else "测试失败")

                test_button.configure(command=test_feishu_clicked)
                test_button.pack(side="right", padx=(0, 8))
                settings_button = original_button(frame, text="统一配置", width=10, command=lambda: _show_unified_settings_window(root))
                settings_button.pack(side="right", padx=(0, 8))
            except Exception as exc:
                _log("WARN", "添加停止按钮失败", error=_safe_error_text(exc))

        root.after(800, add_stop_button)
        return root

    tk.Tk = tk_with_stop_button
    tk.Button = tracked_button
    try:
        _base_show_pipeline_control_panel()
    finally:
        tk.Tk = original_tk
        tk.Button = original_button


def _install_stop_button_runtime_patches() -> None:
    BASE["LEGACY"]["DxmTemuRobot"] = StoppableDxmTemuRobot
    BASE["patched_fill_basic_required_attrs"] = fill_basic_required_attrs_product_attrs_only
    BASE["ORIGINAL_FILL_BASIC_REQUIRED_ATTRS"] = fill_basic_required_attrs_product_attrs_only
    BASE["_ensure_basic_age_range_rule"] = _skip_basic_age_range_rule
    BASE["LEGACY"]["DxmTemuRobot"].fill_basic_required_attrs = fill_basic_required_attrs_product_attrs_only
    BASE["LEGACY"]["DxmTemuRobot"].scan_basic_attrs = scan_basic_attrs_product_attrs_only
    BASE["_show_pipeline_control_panel"] = _show_pipeline_control_panel_with_stop_button
    BASE["_run_pipeline_step_with_retry"] = _run_pipeline_step_with_retry_stoppable
    BASE["_run_limited_full_pipeline"] = _run_limited_full_pipeline_stoppable
    BASE["_run_full_pipeline"] = _run_full_pipeline_stoppable
    BASE["_run_full_pipeline_with_open_action"] = _run_full_pipeline_with_open_action_stoppable
    BASE["_publish_recorded_edited_pages"] = _publish_recorded_edited_pages_stoppable
    BASE["_select_warehouse_names_playwright"] = _select_warehouse_names_with_self_check
    BASE["_fill_basic_required_attrs_ai_guarded"] = _fill_basic_required_attrs_ai_guarded_with_product_attr_rules
    if callable(_base_manual_menu_for_stop):
        BASE["_manual_menu"] = _manual_menu_stoppable


BASE["_publish_recorded_edited_pages"] = _publish_recorded_edited_pages_stoppable
_install_stop_button_runtime_patches()


def main() -> None:
    if not _acquire_single_instance_lock():
        _show_already_running_message()
        raise SystemExit(0)
    if "--test-feishu" in sys.argv[1:]:
        ok = _send_feishu_text("测试通知", "DxmTemuTerminalRobot 飞书机器人配置可用。", level="INFO")
        raise SystemExit(0 if ok else 1)
    _install_stop_button_runtime_patches()
    BASE["LEGACY"]["DxmTemuRobot"].bind_edit_page = bind_edit_page_prefer_requested
    BASE["LEGACY"]["DxmTemuRobot"].download_product_images = download_product_images_with_postprocess
    BASE["fill_product_description_images_v2"] = fill_product_description_images_replace
    BASE["fill_product_description_images"] = fill_product_description_images_replace
    BASE["_publish_recorded_edited_pages"] = _publish_recorded_edited_pages_stoppable
    BASE["_run_pipeline_step_with_retry"] = _run_pipeline_step_with_retry_stoppable
    BASE["_run_limited_full_pipeline"] = _run_limited_full_pipeline_stoppable
    BASE["_show_pipeline_control_panel"] = _show_pipeline_control_panel_with_stop_button
    BASE["_select_warehouse_names_playwright"] = _select_warehouse_names_with_self_check
    BASE["main"]()


if __name__ == "__main__":
    main()
