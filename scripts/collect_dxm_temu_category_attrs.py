from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


DEFAULT_CDP_URL = "http://127.0.0.1:9222"
DEFAULT_DB_PATH = Path(r"D:\learning\temu_listing_workbench\backend\data\app.db")


READ_CATEGORY_MODAL_JS = r"""
() => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function displayable(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0 && r.height>0 && st.display !== 'none' && st.visibility !== 'hidden';
  }
  const modals=[...document.querySelectorAll('.ant-modal,.ant-modal-wrap,[role="dialog"]')].filter(displayable);
  const modal=modals.find(el => /选择类目|搜索分类名称|选择/.test(clean(el.innerText||el.textContent))) || modals[0];
  if(!modal) return {ok:false,error:'missing modal'};
  const itemNodes=[...modal.querySelectorAll('.categories-item')].filter(displayable);
  const items=itemNodes.map((el, index) => {
    const r=el.getBoundingClientRect();
    const name=clean(el.querySelector('.categories-item-name')?.innerText || el.innerText || el.textContent);
    const cls=String(el.className||'');
    return {
      index,
      text:name,
      x:Math.round(r.x),
      y:Math.round(r.y),
      w:Math.round(r.width),
      h:Math.round(r.height),
      active:cls.includes('active'),
      className:cls
    };
  }).filter(item => item.text);
  const xs=[...new Set(items.map(item => item.x))].sort((a,b)=>a-b);
  const columns=xs.map((x, columnIndex) => ({
    columnIndex,
    x,
    items:items.filter(item => Math.abs(item.x-x)<=8).sort((a,b)=>a.y-b.y)
  }));
  const pathText=clean([...modal.querySelectorAll('div,span')]
    .map(el => clean(el.innerText||el.textContent))
    .find(text => text.includes('>') && !/选择类目|搜索/.test(text)) || '');
  return {ok:true,pathText,columns};
}
"""


OPEN_CATEGORY_MODAL_JS = r"""
() => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function visible(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'
      && r.bottom>=0&&r.right>=0&&r.top<=innerHeight&&r.left<=innerWidth;
  }
  if([...document.querySelectorAll('.ant-modal,.ant-modal-wrap,[role="dialog"]')]
    .filter(visible)
    .some(el => /选择类目|搜索分类名称/.test(clean(el.innerText||el.textContent)))) return {ok:true, alreadyOpen:true};
  const nodes=[...document.querySelectorAll('button,a,span,div')].filter(visible);
  const button=nodes.find(el => clean(el.innerText||el.textContent)==='选择分类')
    || nodes.find(el => clean(el.innerText||el.textContent).includes('选择分类'));
  if(!button) return {ok:false,error:'missing choose category button'};
  button.scrollIntoView({block:'center', inline:'center'});
  const r=button.getBoundingClientRect();
  return {ok:true,x:r.x+r.width/2,y:r.y+r.height/2,text:clean(button.innerText||button.textContent)};
}
"""


CLICK_CATEGORY_ITEM_JS = r"""
({columnIndex, text}) => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function displayable(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0 && r.height>0 && st.display !== 'none' && st.visibility !== 'hidden';
  }
  const modals=[...document.querySelectorAll('.ant-modal,.ant-modal-wrap,[role="dialog"]')].filter(displayable);
  const modal=modals.find(el => /选择类目|搜索分类名称|选择/.test(clean(el.innerText||el.textContent))) || modals[0];
  if(!modal) return {ok:false,error:'missing modal'};
  const itemNodes=[...modal.querySelectorAll('.categories-item')].filter(displayable);
  const items=itemNodes.map(el => {
    const r=el.getBoundingClientRect();
    const name=clean(el.querySelector('.categories-item-name')?.innerText || el.innerText || el.textContent);
    return {el,name,x:Math.round(r.x),y:Math.round(r.y)};
  }).filter(item => item.name);
  const xs=[...new Set(items.map(item => item.x))].sort((a,b)=>a-b);
  const x=xs[columnIndex];
  if(x === undefined) return {ok:false,error:'missing column', columns:xs.length};
  const item=items.find(item => Math.abs(item.x-x)<=8 && item.name === text)
    || items.find(item => Math.abs(item.x-x)<=8 && clean(item.name).includes(text));
  if(!item) return {ok:false,error:'missing item', columnIndex, text, seen:items.filter(item => Math.abs(item.x-x)<=8).map(item => item.name).slice(0,80)};
  item.el.scrollIntoView({block:'center', inline:'center'});
  const r=item.el.getBoundingClientRect();
  return {ok:true,x:r.x+r.width/2,y:r.y+r.height/2,text:item.name,columnIndex};
}
"""


CLICK_MODAL_CHOOSE_JS = r"""
() => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function visible(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden'
      && r.bottom>=0&&r.right>=0&&r.top<=innerHeight&&r.left<=innerWidth;
  }
  const modals=[...document.querySelectorAll('.ant-modal,.ant-modal-wrap,[role="dialog"]')].filter(visible);
  const modal=modals.find(el => /选择类目|搜索分类名称|选择/.test(clean(el.innerText||el.textContent))) || modals[0];
  if(!modal) return {ok:false,error:'missing modal'};
  const buttons=[...modal.querySelectorAll('button,a,span,div')].filter(visible);
  const button=buttons.find(el => clean(el.innerText||el.textContent)==='选择');
  if(!button) return {ok:false,error:'missing choose button'};
  const r=button.getBoundingClientRect();
  return {ok:true,x:r.x+r.width/2,y:r.y+r.height/2,text:clean(button.innerText||button.textContent)};
}
"""


READ_PINIA_CATEGORIES_JS = r"""
() => {
  const app = document.querySelector('#app')?.__vue_app__;
  const pinia = app?.config?.globalProperties?.$pinia;
  const state = pinia?.state?.value || {};
  const basic = state.temuAddBasicStore || {};
  const form = basic.formState || {};
  const data = basic.dataState || {};
  const categories = (data.categories || [])
    .filter(item => item && item.categoryId && item.nodePath)
    .map(item => ({
      categoryId: String(item.categoryId || ''),
      categoryPathText: String(item.nodePath || '').split('/').filter(Boolean).join(' > '),
      nodePath: String(item.nodePath || ''),
      nodePathId: String(item.nodePathId || ''),
      label: String(item.label || item.nameZh || item.nameEn || ''),
      catLevel: Number(item.catLevel || 0),
      raw: item
    }));
  const seen = new Set();
  const unique = [];
  for (const item of categories) {
    if (!item.categoryId || seen.has(item.categoryId)) continue;
    seen.add(item.categoryId);
    unique.push(item);
  }
  unique.sort((a, b) => a.categoryPathText.localeCompare(b.categoryPathText, 'zh-Hans-CN'));
  return {ok: true, shopId: String(form.shopId || ''), categories: unique};
}
"""


FETCH_CATEGORY_ATTRS_API_JS = r"""
async ({categoryId, shopId}) => {
  const body = new URLSearchParams({categoryId: String(categoryId || ''), shopId: String(shopId || '')}).toString();
  const res = await fetch('/api/popTemuCategory/attributeList.json', {
    method: 'POST',
    credentials: 'include',
    headers: {'content-type': 'application/x-www-form-urlencoded; charset=UTF-8'},
    body
  });
  const text = await res.text();
  let json;
  try { json = JSON.parse(text); } catch (error) { return {ok: false, status: res.status, error: 'invalid_json', text: text.slice(0, 800)}; }
  if (String(json.code) !== '0') return {ok: false, status: res.status, code: json.code, msg: json.msg, data: json.data};
  return {ok: true, status: res.status, data: Array.isArray(json.data) ? json.data : []};
}
"""


FETCH_CATEGORY_CHILDREN_API_JS = r"""
async ({shopId, parentId}) => {
  const body = new URLSearchParams();
  if (shopId) body.set('shopId', String(shopId));
  if (parentId !== undefined && parentId !== null && parentId !== '') {
    body.set('categoryParentId', String(parentId));
  }
  const res = await fetch('/api/popTemuCategory/list.json', {
    method: 'POST',
    credentials: 'include',
    headers: {'content-type': 'application/x-www-form-urlencoded; charset=UTF-8'},
    body: body.toString()
  });
  const text = await res.text();
  let json;
  try { json = JSON.parse(text); } catch (error) {
    return {ok: false, status: res.status, error: 'invalid_json', text: text.slice(0, 800)};
  }
  if (json && json.code !== undefined && String(json.code) !== '0') {
    return {ok: false, status: res.status, code: json.code, msg: json.msg, data: json.data};
  }
  const candidates = [
    json,
    json?.data,
    json?.result,
    json?.rows,
    json?.list,
    json?.data?.list,
    json?.data?.rows,
    json?.result?.list,
    json?.result?.rows
  ];
  const data = candidates.find(item => Array.isArray(item)) || [];
  return {ok: true, status: res.status, data};
}
"""


READ_SHOP_ID_JS = r"""
() => {
  const app = document.querySelector('#app')?.__vue_app__;
  const pinia = app?.config?.globalProperties?.$pinia;
  const state = pinia?.state?.value || {};
  return {
    ok: true,
    shopId: String(state.temuAddBasicStore?.formState?.shopId || '')
  };
}
"""


SCAN_PRODUCT_ATTRS_JS = r"""
() => {
  function clean(s){return (s||'').replace(/[\n\r\t]+/g,' ').replace(/\s+/g,' ').trim()}
  function visible(el){
    if(!el) return false;
    const r=el.getBoundingClientRect();
    const st=getComputedStyle(el);
    return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden';
  }
  function labelOf(item){
    const label=item.querySelector('[class*="attr-label"],.ant-form-item-label,[class*="form-item-label"],label');
    let text=clean(label?.innerText || label?.textContent || '');
    text=text.replace(/^[*＊\s]+/,'').replace(/[:：]$/,'').trim();
    return text;
  }
  function componentOf(item){
    if(item.querySelector('.ant-checkbox-wrapper,input[type="checkbox"]')) return 'checkbox-group';
    if(item.querySelector('.ant-select')) return 'ant-select';
    if(item.querySelector('textarea')) return 'textarea';
    if(item.querySelector('input')) return 'input';
    return 'unknown';
  }
  function valueOf(item, component){
    if(component === 'ant-select'){
      return clean(item.querySelector('.ant-select-selection-item')?.innerText
        || item.querySelector('.ant-select-selection-placeholder')?.innerText
        || '');
    }
    if(component === 'checkbox-group'){
      return [...item.querySelectorAll('.ant-checkbox-wrapper,input[type="checkbox"]')]
        .map(el => {
          const wrapper=el.closest?.('.ant-checkbox-wrapper') || el;
          const input=wrapper.querySelector?.('input[type="checkbox"]') || (el.matches?.('input[type="checkbox"]') ? el : null);
          return input && input.checked ? clean(wrapper.innerText || wrapper.textContent) : '';
        })
        .filter(Boolean)
        .join('|');
    }
    const input=item.querySelector('textarea,input');
    return clean(input?.value || input?.getAttribute('value') || '');
  }
  function placeholderOf(item, component){
    if(component === 'ant-select') return clean(item.querySelector('.ant-select-selection-placeholder')?.innerText || '');
    const input=item.querySelector('textarea,input');
    return clean(input?.getAttribute('placeholder') || '');
  }
  const categoryText=clean(document.querySelector('.category-list-color,[class*="category-list"]')?.innerText || '');
  const root=document.querySelector('#productBasicInfo .product-attrs') || document.querySelector('.product-attrs');
  if(!root) return {ok:false,error:'missing product attrs root',categoryText};
  const candidates=[...root.querySelectorAll('.attr-form-item,.ant-form-item,[class*="form-item"]')].filter(visible);
  const fields=[];
  const seen=new Set();
  for(const item of candidates){
    const label=labelOf(item);
    if(!label || seen.has(label)) continue;
    const component=componentOf(item);
    if(component === 'unknown') continue;
    seen.add(label);
    const required=/^[\s\n\r]*[*＊]/.test((item.innerText || item.textContent || '')) || !!item.querySelector('[class*="required"]');
    const options=[...item.querySelectorAll('.ant-checkbox-wrapper,label')]
      .map(el => clean(el.innerText || el.textContent))
      .filter(text => text && text !== label && text.length <= 80);
    fields.push({
      label,
      required,
      component,
      value:valueOf(item, component),
      placeholder:placeholderOf(item, component),
      options:[...new Set(options)],
      rawText:clean(item.innerText || item.textContent).slice(0,500)
    });
  }
  return {ok:true,categoryText,fields};
}
"""


def now_text() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat(sep=" ")


def category_key(path_text: str) -> str:
    normalized = " > ".join(part.strip() for part in path_text.split(">") if part.strip())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:20]


def split_category_path(value: str) -> list[str]:
    return [
        part.strip()
        for part in str(value or "").replace("/", ">").split(">")
        if part.strip()
    ]


def split_node_path_ids(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split("/") if part.strip()]


def category_binding(path_text: str, category: dict[str, Any] | None = None) -> dict[str, Any]:
    names = split_category_path(path_text)
    ids = split_node_path_ids(str((category or {}).get("nodePathId") or ""))
    category_id = str((category or {}).get("categoryId") or (ids[-1] if ids else "")).strip()
    binding: dict[str, Any] = {
        "category_id": category_id,
        "node_path_id": "/".join(ids),
        "category_depth": len(names),
    }
    for index in range(6):
        level = index + 1
        binding[f"level{level}_name"] = names[index] if index < len(names) else ""
        binding[f"level{level}_id"] = ids[index] if index < len(ids) else ""
    return binding


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {str(row[1]) for row in rows}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS dxm_temu_category_attr_snapshots (
            id TEXT PRIMARY KEY,
            site TEXT NOT NULL DEFAULT '美国站',
            category_key TEXT NOT NULL,
            category_id TEXT NOT NULL DEFAULT '',
            category_path_text TEXT NOT NULL,
            category_path_json TEXT NOT NULL,
            node_path_id TEXT NOT NULL DEFAULT '',
            category_depth INTEGER NOT NULL DEFAULT 0,
            level1_id TEXT NOT NULL DEFAULT '',
            level1_name TEXT NOT NULL DEFAULT '',
            level2_id TEXT NOT NULL DEFAULT '',
            level2_name TEXT NOT NULL DEFAULT '',
            level3_id TEXT NOT NULL DEFAULT '',
            level3_name TEXT NOT NULL DEFAULT '',
            level4_id TEXT NOT NULL DEFAULT '',
            level4_name TEXT NOT NULL DEFAULT '',
            level5_id TEXT NOT NULL DEFAULT '',
            level5_name TEXT NOT NULL DEFAULT '',
            level6_id TEXT NOT NULL DEFAULT '',
            level6_name TEXT NOT NULL DEFAULT '',
            leaf_name TEXT NOT NULL,
            attr_count INTEGER NOT NULL DEFAULT 0,
            required_count INTEGER NOT NULL DEFAULT 0,
            collection_status TEXT NOT NULL DEFAULT 'ok',
            collection_error TEXT NOT NULL DEFAULT '',
            attributes_json TEXT NOT NULL DEFAULT '[]',
            source_edit_url TEXT,
            collected_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(site, category_path_text)
        );

        CREATE TABLE IF NOT EXISTS dxm_temu_category_attr_fields (
            id TEXT PRIMARY KEY,
            site TEXT NOT NULL DEFAULT '美国站',
            category_key TEXT NOT NULL,
            category_id TEXT NOT NULL DEFAULT '',
            category_path_text TEXT NOT NULL,
            node_path_id TEXT NOT NULL DEFAULT '',
            category_depth INTEGER NOT NULL DEFAULT 0,
            level1_id TEXT NOT NULL DEFAULT '',
            level1_name TEXT NOT NULL DEFAULT '',
            level2_id TEXT NOT NULL DEFAULT '',
            level2_name TEXT NOT NULL DEFAULT '',
            level3_id TEXT NOT NULL DEFAULT '',
            level3_name TEXT NOT NULL DEFAULT '',
            level4_id TEXT NOT NULL DEFAULT '',
            level4_name TEXT NOT NULL DEFAULT '',
            level5_id TEXT NOT NULL DEFAULT '',
            level5_name TEXT NOT NULL DEFAULT '',
            level6_id TEXT NOT NULL DEFAULT '',
            level6_name TEXT NOT NULL DEFAULT '',
            field_key TEXT NOT NULL,
            field_label TEXT NOT NULL,
            required INTEGER NOT NULL DEFAULT 0,
            component TEXT NOT NULL DEFAULT '',
            current_value TEXT NOT NULL DEFAULT '',
            placeholder TEXT NOT NULL DEFAULT '',
            options_json TEXT NOT NULL DEFAULT '[]',
            option_count INTEGER NOT NULL DEFAULT 0,
            raw_json TEXT NOT NULL DEFAULT '{}',
            collected_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(site, category_path_text, field_key)
        );

        CREATE INDEX IF NOT EXISTS idx_dxm_temu_category_attr_snapshots_key
            ON dxm_temu_category_attr_snapshots(category_key);
        CREATE INDEX IF NOT EXISTS idx_dxm_temu_category_attr_fields_key
            ON dxm_temu_category_attr_fields(category_key);
        CREATE INDEX IF NOT EXISTS idx_dxm_temu_category_attr_fields_label
            ON dxm_temu_category_attr_fields(field_label);
        """
    )
    binding_columns = [
        ("category_id", "TEXT NOT NULL DEFAULT ''"),
        ("node_path_id", "TEXT NOT NULL DEFAULT ''"),
        ("category_depth", "INTEGER NOT NULL DEFAULT 0"),
        ("level1_id", "TEXT NOT NULL DEFAULT ''"),
        ("level1_name", "TEXT NOT NULL DEFAULT ''"),
        ("level2_id", "TEXT NOT NULL DEFAULT ''"),
        ("level2_name", "TEXT NOT NULL DEFAULT ''"),
        ("level3_id", "TEXT NOT NULL DEFAULT ''"),
        ("level3_name", "TEXT NOT NULL DEFAULT ''"),
        ("level4_id", "TEXT NOT NULL DEFAULT ''"),
        ("level4_name", "TEXT NOT NULL DEFAULT ''"),
        ("level5_id", "TEXT NOT NULL DEFAULT ''"),
        ("level5_name", "TEXT NOT NULL DEFAULT ''"),
        ("level6_id", "TEXT NOT NULL DEFAULT ''"),
        ("level6_name", "TEXT NOT NULL DEFAULT ''"),
    ]
    for table in ("dxm_temu_category_attr_snapshots", "dxm_temu_category_attr_fields"):
        for column, ddl in binding_columns:
            ensure_column(conn, table, column, ddl)
    ensure_column(conn, "dxm_temu_category_attr_snapshots", "collection_status", "TEXT NOT NULL DEFAULT 'ok'")
    ensure_column(conn, "dxm_temu_category_attr_snapshots", "collection_error", "TEXT NOT NULL DEFAULT ''")
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_dxm_temu_category_attr_snapshots_category_id
            ON dxm_temu_category_attr_snapshots(category_id);
        CREATE INDEX IF NOT EXISTS idx_dxm_temu_category_attr_fields_category_id
            ON dxm_temu_category_attr_fields(category_id);
        CREATE INDEX IF NOT EXISTS idx_dxm_temu_category_attr_snapshots_levels_1_4
            ON dxm_temu_category_attr_snapshots(level1_name, level2_name, level3_name, level4_name);
        CREATE INDEX IF NOT EXISTS idx_dxm_temu_category_attr_fields_levels_1_4
            ON dxm_temu_category_attr_fields(level1_name, level2_name, level3_name, level4_name);
        """
    )


def existing_category_paths(conn: sqlite3.Connection, *, site: str) -> set[str]:
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT category_path_text FROM dxm_temu_category_attr_snapshots WHERE site = ?",
        (site,),
    ).fetchall()
    return {str(row[0] or "").strip() for row in rows if str(row[0] or "").strip()}


def upsert_category_attrs(
    conn: sqlite3.Connection,
    *,
    site: str,
    path_text: str,
    attrs: list[dict[str, Any]],
    source_url: str,
    category: dict[str, Any] | None = None,
    collection_status: str = "ok",
    collection_error: str = "",
) -> None:
    parts = split_category_path(path_text)
    binding = category_binding(path_text, category)
    key = category_key(path_text)
    timestamp = now_text()
    snapshot_id = f"{site}:{key}"
    required_count = sum(1 for item in attrs if item.get("required"))
    conn.execute(
        """
        INSERT INTO dxm_temu_category_attr_snapshots (
            id, site, category_key, category_id, category_path_text, category_path_json,
            node_path_id, category_depth,
            level1_id, level1_name, level2_id, level2_name, level3_id, level3_name,
            level4_id, level4_name, level5_id, level5_name, level6_id, level6_name,
            leaf_name,
            attr_count, required_count, collection_status, collection_error,
            attributes_json, source_edit_url, collected_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(site, category_path_text) DO UPDATE SET
            category_key=excluded.category_key,
            category_id=excluded.category_id,
            category_path_json=excluded.category_path_json,
            node_path_id=excluded.node_path_id,
            category_depth=excluded.category_depth,
            level1_id=excluded.level1_id,
            level1_name=excluded.level1_name,
            level2_id=excluded.level2_id,
            level2_name=excluded.level2_name,
            level3_id=excluded.level3_id,
            level3_name=excluded.level3_name,
            level4_id=excluded.level4_id,
            level4_name=excluded.level4_name,
            level5_id=excluded.level5_id,
            level5_name=excluded.level5_name,
            level6_id=excluded.level6_id,
            level6_name=excluded.level6_name,
            leaf_name=excluded.leaf_name,
            attr_count=excluded.attr_count,
            required_count=excluded.required_count,
            collection_status=excluded.collection_status,
            collection_error=excluded.collection_error,
            attributes_json=excluded.attributes_json,
            source_edit_url=excluded.source_edit_url,
            updated_at=excluded.updated_at
        """,
        (
            snapshot_id,
            site,
            key,
            binding["category_id"],
            path_text,
            json.dumps(parts, ensure_ascii=False),
            binding["node_path_id"],
            binding["category_depth"],
            binding["level1_id"],
            binding["level1_name"],
            binding["level2_id"],
            binding["level2_name"],
            binding["level3_id"],
            binding["level3_name"],
            binding["level4_id"],
            binding["level4_name"],
            binding["level5_id"],
            binding["level5_name"],
            binding["level6_id"],
            binding["level6_name"],
            parts[-1] if parts else "",
            len(attrs),
            required_count,
            collection_status,
            collection_error,
            json.dumps(attrs, ensure_ascii=False),
            source_url,
            timestamp,
            timestamp,
        ),
    )
    current_field_keys: set[str] = set()
    for attr in attrs:
        label = str(attr.get("label") or "").strip()
        if not label:
            continue
        source_field_id = str(attr.get("attributeId") or attr.get("id") or "").strip()
        field_key_source = source_field_id or label
        field_key = hashlib.sha1(field_key_source.encode("utf-8")).hexdigest()[:20]
        current_field_keys.add(field_key)
        field_id = f"{site}:{key}:{field_key}"
        options = attr.get("options") if isinstance(attr.get("options"), list) else []
        conn.execute(
            """
            INSERT INTO dxm_temu_category_attr_fields (
                id, site, category_key, category_id, category_path_text,
                node_path_id, category_depth,
                level1_id, level1_name, level2_id, level2_name, level3_id, level3_name,
                level4_id, level4_name, level5_id, level5_name, level6_id, level6_name,
                field_key, field_label,
                required, component, current_value, placeholder, options_json, option_count,
                raw_json, collected_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(site, category_path_text, field_key) DO UPDATE SET
                category_key=excluded.category_key,
                category_id=excluded.category_id,
                node_path_id=excluded.node_path_id,
                category_depth=excluded.category_depth,
                level1_id=excluded.level1_id,
                level1_name=excluded.level1_name,
                level2_id=excluded.level2_id,
                level2_name=excluded.level2_name,
                level3_id=excluded.level3_id,
                level3_name=excluded.level3_name,
                level4_id=excluded.level4_id,
                level4_name=excluded.level4_name,
                level5_id=excluded.level5_id,
                level5_name=excluded.level5_name,
                level6_id=excluded.level6_id,
                level6_name=excluded.level6_name,
                field_label=excluded.field_label,
                required=excluded.required,
                component=excluded.component,
                current_value=excluded.current_value,
                placeholder=excluded.placeholder,
                options_json=excluded.options_json,
                option_count=excluded.option_count,
                raw_json=excluded.raw_json,
                updated_at=excluded.updated_at
            """,
            (
                field_id,
                site,
                key,
                binding["category_id"],
                path_text,
                binding["node_path_id"],
                binding["category_depth"],
                binding["level1_id"],
                binding["level1_name"],
                binding["level2_id"],
                binding["level2_name"],
                binding["level3_id"],
                binding["level3_name"],
                binding["level4_id"],
                binding["level4_name"],
                binding["level5_id"],
                binding["level5_name"],
                binding["level6_id"],
                binding["level6_name"],
                field_key,
                label,
                1 if attr.get("required") else 0,
                str(attr.get("component") or ""),
                str(attr.get("value") or ""),
                str(attr.get("placeholder") or ""),
                json.dumps(options, ensure_ascii=False),
                len(options),
                json.dumps(attr, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
    if current_field_keys:
        placeholders = ", ".join("?" for _ in current_field_keys)
        conn.execute(
            f"""
            DELETE FROM dxm_temu_category_attr_fields
            WHERE site = ?
              AND category_path_text = ?
              AND field_key NOT IN ({placeholders})
            """,
            (site, path_text, *sorted(current_field_keys)),
        )
    else:
        conn.execute(
            """
            DELETE FROM dxm_temu_category_attr_fields
            WHERE site = ?
              AND category_path_text = ?
            """,
            (site, path_text),
        )


def find_edit_page(browser: Any) -> Any:
    pages = [page for context in browser.contexts for page in context.pages]
    page = next((item for item in pages if "/web/popTemu/edit" in item.url), None)
    if page is not None:
        return page
    draft = next((item for item in pages if "/web/popTemu/pageList/draft" in item.url), None)
    if draft is None:
        raise RuntimeError("没有找到店小秘 Temu 编辑页或草稿列表页")
    draft.bring_to_front()
    context = draft.context
    buttons = draft.locator("button:has-text('编辑'), a:has-text('编辑'), span:has-text('编辑')")
    if buttons.count() <= 0:
        raise RuntimeError("草稿列表没有找到编辑按钮")
    try:
        with context.expect_page(timeout=5000) as new_page_info:
            buttons.nth(0).click(timeout=5000)
        page = new_page_info.value
    except PlaywrightTimeoutError:
        buttons.nth(0).click(timeout=5000)
        time.sleep(2)
        pages = [item for ctx in browser.contexts for item in ctx.pages]
        page = next((item for item in pages if "/web/popTemu/edit" in item.url), draft)
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    time.sleep(1.5)
    return page


def open_category_modal(page: Any) -> dict[str, Any]:
    point = page.evaluate(OPEN_CATEGORY_MODAL_JS)
    if not isinstance(point, dict) or not point.get("ok"):
        raise RuntimeError(f"打开类目弹窗失败：{point}")
    if not point.get("alreadyOpen"):
        page.mouse.click(float(point["x"]), float(point["y"]))
        time.sleep(0.8)
    state = page.evaluate(READ_CATEGORY_MODAL_JS)
    if not isinstance(state, dict) or not state.get("ok"):
        raise RuntimeError(f"读取类目弹窗失败：{state}")
    return state


def click_category_item(page: Any, column_index: int, text: str) -> None:
    last: Any = None
    for _ in range(3):
        point = page.evaluate(CLICK_CATEGORY_ITEM_JS, {"columnIndex": column_index, "text": text})
        last = point
        if not isinstance(point, dict) or not point.get("ok"):
            time.sleep(0.25)
            continue
        page.mouse.click(float(point["x"]), float(point["y"]))
        for _wait in range(12):
            time.sleep(0.2)
            state = page.evaluate(READ_CATEGORY_MODAL_JS)
            if not isinstance(state, dict) or not state.get("ok"):
                continue
            columns = state.get("columns") if isinstance(state.get("columns"), list) else []
            if column_index >= len(columns):
                continue
            column = columns[column_index] if isinstance(columns[column_index], dict) else {}
            active = next(
                (
                    item
                    for item in column.get("items") or []
                    if isinstance(item, dict) and item.get("active") and str(item.get("text") or "").strip() == text
                ),
                None,
            )
            if active:
                return
        last = {"ok": False, "error": "active_state_not_updated", "columnIndex": column_index, "text": text}
    raise RuntimeError(f"点击类目失败：{last}")


def click_modal_choose(page: Any) -> None:
    point = page.evaluate(CLICK_MODAL_CHOOSE_JS)
    if not isinstance(point, dict) or not point.get("ok"):
        raise RuntimeError(f"点击选择失败：{point}")
    page.mouse.click(float(point["x"]), float(point["y"]))
    time.sleep(1.4)


def active_path_from_state(state: dict[str, Any]) -> list[str]:
    path: list[str] = []
    for column in state.get("columns") or []:
        items = column.get("items") if isinstance(column, dict) else []
        active = next((item for item in items if isinstance(item, dict) and item.get("active")), None)
        if active:
            path.append(str(active.get("text") or "").strip())
    return [item for item in path if item]


def current_branch_leaf_paths(state: dict[str, Any]) -> list[list[str]]:
    path = active_path_from_state(state)
    columns = [col for col in (state.get("columns") or []) if isinstance(col, dict)]
    if not columns:
        return []
    last_col = columns[-1]
    last_items = [item for item in (last_col.get("items") or []) if isinstance(item, dict)]
    last_col_has_active = any(bool(item.get("active")) for item in last_items)
    prefix = path[:-1] if last_col_has_active and path else path
    leaves: list[list[str]] = []
    seen: set[str] = set()
    for item in last_items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        leaves.append([*prefix, text])
    return leaves


def navigate_modal_path(page: Any, path: list[str]) -> None:
    open_category_modal(page)
    for index, part in enumerate(path):
        click_category_item(page, index, part)
    state = page.evaluate(READ_CATEGORY_MODAL_JS)
    if not isinstance(state, dict) or not state.get("ok"):
        raise RuntimeError(f"选择类目路径后读取失败：{state}")


def child_items_for_path(page: Any, path: list[str]) -> list[str]:
    navigate_modal_path(page, path)
    state = page.evaluate(READ_CATEGORY_MODAL_JS)
    if not isinstance(state, dict) or not state.get("ok"):
        raise RuntimeError(f"读取子类目失败：{state}")
    columns = [col for col in (state.get("columns") or []) if isinstance(col, dict)]
    child_index = len(path)
    if child_index >= len(columns):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for item in columns[child_index].get("items") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def path_has_children(page: Any, path: list[str]) -> bool:
    navigate_modal_path(page, path)
    state = page.evaluate(READ_CATEGORY_MODAL_JS)
    if not isinstance(state, dict) or not state.get("ok"):
        return False
    active = active_path_from_state(state)
    columns = [col for col in (state.get("columns") or []) if isinstance(col, dict)]
    child_index = len(active)
    return child_index < len(columns) and bool(columns[child_index].get("items"))


def collect_descendant_leaf_paths(page: Any, root_path: list[str], limit: int) -> list[list[str]]:
    leaves: list[list[str]] = []

    def walk(path: list[str]) -> None:
        if limit > 0 and len(leaves) >= limit:
            return
        children = child_items_for_path(page, path)
        if not children:
            leaves.append(path)
            return
        for child in children:
            candidate = [*path, child]
            if path_has_children(page, candidate):
                walk(candidate)
            else:
                leaves.append(candidate)
            if limit > 0 and len(leaves) >= limit:
                return

    walk(root_path)
    return leaves


def iter_descendant_leaf_paths(page: Any, root_path: list[str], limit: int):
    emitted = 0

    def walk(path: list[str]):
        nonlocal emitted
        if limit > 0 and emitted >= limit:
            return
        children = child_items_for_path(page, path)
        if not children:
            emitted += 1
            yield path
            return
        for child in children:
            if limit > 0 and emitted >= limit:
                return
            candidate = [*path, child]
            if path_has_children(page, candidate):
                yield from walk(candidate)
            else:
                emitted += 1
                yield candidate

    yield from walk(root_path)


def scan_product_attrs(page: Any) -> dict[str, Any]:
    for _ in range(15):
        state = page.evaluate(SCAN_PRODUCT_ATTRS_JS)
        if isinstance(state, dict) and state.get("ok"):
            return state
        time.sleep(0.4)
    raise RuntimeError(f"扫描产品属性失败：{state}")


def wait_category_text(page: Any, expected_path: str, *, timeout: float = 12.0) -> str:
    deadline = time.time() + timeout
    last = ""
    normalized_expected = " > ".join(part.strip() for part in expected_path.split(">") if part.strip())
    while time.time() < deadline:
        state = page.evaluate(SCAN_PRODUCT_ATTRS_JS)
        if isinstance(state, dict):
            last = str(state.get("categoryText") or "").strip()
            normalized_last = " > ".join(part.strip() for part in last.split(">") if part.strip())
            if normalized_last == normalized_expected:
                return last
        time.sleep(0.4)
    raise RuntimeError(f"类目选择后页面回显不一致：expected={normalized_expected} actual={last}")


def collect_paths(page: Any, mode: str, limit: int) -> list[list[str]]:
    state = open_category_modal(page)
    if mode == "current":
        path = active_path_from_state(state)
        return [path] if path else []
    if mode == "current-branch":
        active = active_path_from_state(state)
        columns = [col for col in (state.get("columns") or []) if isinstance(col, dict)]
        if not active:
            return []
        if len(columns) > len(active):
            root_path = active
        else:
            root_path = active[:-1] if len(active) > 1 else active
        return collect_descendant_leaf_paths(page, root_path, limit)
    raise RuntimeError(f"暂不支持 mode={mode}")


def parse_jsonish(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return default


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}


def intish(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(str(value).strip()))
    except Exception:
        return default


def normalize_api_options(raw: dict[str, Any]) -> list[dict[str, Any]]:
    values = parse_jsonish(raw.get("values"), [])
    translates = parse_jsonish(raw.get("valuesTranslate"), [])
    if not isinstance(values, list):
        return []
    translate_by_vid: dict[str, dict[str, Any]] = {}
    if isinstance(translates, list):
        for item in translates:
            if isinstance(item, dict) and item.get("vid") is not None:
                translate_by_vid[str(item.get("vid"))] = item
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        vid = str(item.get("vid") or item.get("id") or "").strip()
        lang = item.get("lang2Value") if isinstance(item.get("lang2Value"), dict) else {}
        text = str(item.get("value") or lang.get("zh-Hans") or lang.get("en") or "").strip()
        if not text and vid in translate_by_vid:
            text = str(translate_by_vid[vid].get("original_value") or translate_by_vid[vid].get("translate_value") or "").strip()
        if not text:
            continue
        key = vid or text
        if key in seen:
            continue
        seen.add(key)
        translated = translate_by_vid.get(vid, {})
        options.append(
            {
                "vid": vid,
                "value": text,
                "label": text,
                "en": str(lang.get("en") or translated.get("translate_value") or "").strip(),
                "ja": str(lang.get("ja") or "").strip(),
                "group": item.get("group"),
                "specId": item.get("specId"),
                "extendInfo": item.get("extendInfo"),
            }
        )
    return options


def normalize_api_component(raw: dict[str, Any], options: list[dict[str, Any]]) -> str:
    label = str(raw.get("name") or "").strip()
    control_type = str(raw.get("controlType") or "").strip()
    choose_max = intish(raw.get("chooseMaxNum"))
    if control_type == "16":
        return "select-percent"
    if control_type == "5":
        return "time-input"
    if control_type == "99":
        return "textarea-tag"
    if options:
        return "checkbox-group" if choose_max > 1 else "ant-select"
    if label == "品牌名":
        return "brand-select"
    if intish(raw.get("inputMaxNum")) > 1:
        return "multi-input"
    return "input"


def normalize_api_attr(raw: dict[str, Any]) -> dict[str, Any]:
    options = normalize_api_options(raw)
    label = str(raw.get("name") or "").strip()
    name_translate = parse_jsonish(raw.get("nameTranslate"), {})
    value_units = parse_jsonish(raw.get("valueUnit"), [])
    component = normalize_api_component(raw, options)
    return {
        "id": str(raw.get("id") or "").strip(),
        "attributeId": str(raw.get("attributeId") or raw.get("id") or "").strip(),
        "catId": str(raw.get("catId") or "").strip(),
        "pid": str(raw.get("pid") or "").strip(),
        "templatePid": str(raw.get("templatePid") or "").strip(),
        "label": label,
        "labelEn": str(name_translate.get("en") or raw.get("nameEn") or "").strip() if isinstance(name_translate, dict) else "",
        "required": boolish(raw.get("required")),
        "component": component,
        "controlType": str(raw.get("controlType") or "").strip(),
        "chooseMaxNum": intish(raw.get("chooseMaxNum")),
        "inputMaxNum": intish(raw.get("inputMaxNum")),
        "minValue": raw.get("minValue"),
        "maxValue": raw.get("maxValue"),
        "valueRule": raw.get("valueRule"),
        "valueUnits": value_units if isinstance(value_units, list) else [],
        "options": options,
        "optionCount": len(options),
        "value": "",
        "placeholder": "",
        "raw": raw,
    }


def normalize_api_attrs(raw_attrs: list[Any]) -> list[dict[str, Any]]:
    attrs: list[dict[str, Any]] = []
    for item in raw_attrs:
        if isinstance(item, dict):
            attr = normalize_api_attr(item)
            if attr.get("label"):
                attrs.append(attr)
    return attrs


def read_shop_id(page: Any) -> str:
    state = page.evaluate(READ_SHOP_ID_JS)
    if not isinstance(state, dict) or not state.get("ok"):
        raise RuntimeError(f"read shopId failed: {state}")
    return str(state.get("shopId") or "").strip()


def read_cached_categories(page: Any, *, root_path_text: str = "", limit: int = 0) -> tuple[str, list[dict[str, Any]]]:
    state = page.evaluate(READ_PINIA_CATEGORIES_JS)
    if not isinstance(state, dict) or not state.get("ok"):
        raise RuntimeError(f"读取 Pinia 类目缓存失败：{state}")
    shop_id = str(state.get("shopId") or "").strip()
    categories = state.get("categories") if isinstance(state.get("categories"), list) else []
    normalized_root = " > ".join(split_category_path(root_path_text))
    result: list[dict[str, Any]] = []
    for item in categories:
        if not isinstance(item, dict):
            continue
        path_text = str(item.get("categoryPathText") or "").strip()
        category_id = str(item.get("categoryId") or "").strip()
        if not path_text or not category_id:
            continue
        if normalized_root and not path_text.startswith(normalized_root):
            continue
        result.append(item)
        if limit > 0 and len(result) >= limit:
            break
    return shop_id, result


def normalize_api_category(
    raw: dict[str, Any],
    *,
    parent_names: list[str],
    parent_ids: list[str],
) -> dict[str, Any]:
    category_id = str(raw.get("catId") or raw.get("categoryId") or raw.get("id") or "").strip()
    name = str(raw.get("catName") or raw.get("categoryName") or raw.get("name") or "").strip()
    names = [*parent_names, name] if name else [*parent_names]
    ids = [*parent_ids, category_id] if category_id else [*parent_ids]
    return {
        "categoryId": category_id,
        "categoryPathText": " > ".join(names),
        "nodePath": "/".join(names),
        "nodePathId": "/".join(ids),
        "label": name,
        "catLevel": intish(raw.get("catLevel"), len(names)),
        "parentCatId": str(raw.get("parentCatId") or raw.get("categoryParentId") or "").strip(),
        "isLeaf": boolish(raw.get("isLeaf")),
        "raw": raw,
    }


def fetch_category_children_by_api(page: Any, *, shop_id: str, parent_id: str = "") -> list[dict[str, Any]]:
    result: Any = None
    for attempt in range(1, 6):
        result = page.evaluate(FETCH_CATEGORY_CHILDREN_API_JS, {"shopId": shop_id, "parentId": parent_id})
        if isinstance(result, dict) and result.get("ok"):
            break
        time.sleep(min(0.5 * attempt, 3.0))
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError(f"category list failed parentId={parent_id or '<root>'} result={result}")
    data = result.get("data")
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def iter_category_tree_leaves_by_api(page: Any, *, shop_id: str, root_path_text: str = "", limit: int = 0):
    root_parts = split_category_path(root_path_text)
    emitted = 0
    visited_parent_ids: set[str] = set()

    def may_match_root(path_names: list[str]) -> bool:
        if not root_parts:
            return True
        prefix_len = min(len(path_names), len(root_parts))
        return path_names[:prefix_len] == root_parts[:prefix_len]

    def under_root(path_names: list[str]) -> bool:
        return not root_parts or path_names[: len(root_parts)] == root_parts

    def walk(parent_id: str, parent_names: list[str], parent_ids: list[str]):
        nonlocal emitted
        if limit > 0 and emitted >= limit:
            return
        visit_key = parent_id or "<root>"
        if visit_key in visited_parent_ids:
            return
        visited_parent_ids.add(visit_key)
        children = fetch_category_children_by_api(page, shop_id=shop_id, parent_id=parent_id)
        for raw in children:
            if limit > 0 and emitted >= limit:
                return
            category = normalize_api_category(raw, parent_names=parent_names, parent_ids=parent_ids)
            path_names = split_category_path(str(category.get("categoryPathText") or ""))
            if not category.get("categoryId") or not category.get("label") or not may_match_root(path_names):
                continue
            if category.get("isLeaf"):
                if under_root(path_names):
                    emitted += 1
                    yield category
                continue
            child_count = 0
            child_parent_ids = split_node_path_ids(str(category.get("nodePathId") or ""))
            for leaf in walk(str(category["categoryId"]), path_names, child_parent_ids):
                child_count += 1
                yield leaf
            if child_count == 0 and under_root(path_names):
                emitted += 1
                yield category

    yield from walk("", [], [])


def fetch_category_attrs_by_api(page: Any, *, category_id: str, shop_id: str) -> list[dict[str, Any]]:
    result: Any = None
    for attempt in range(1, 6):
        result = page.evaluate(FETCH_CATEGORY_ATTRS_API_JS, {"categoryId": category_id, "shopId": shop_id})
        if isinstance(result, dict) and result.get("ok"):
            break
        time.sleep(min(0.5 * attempt, 3.0))
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError(f"attributeList 接口失败 categoryId={category_id} result={result}")
    data = result.get("data")
    return normalize_api_attrs(data if isinstance(data, list) else [])


def collect_category_tree_by_api(page: Any, conn: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    shop_id = read_shop_id(page)
    if not shop_id:
        raise RuntimeError("missing shopId; cannot call category tree API")
    verbose = not getattr(args, "quiet", False)
    existing = existing_category_paths(conn, site=args.site) if args.skip_existing else set()
    collected: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    skipped = 0
    seen_leaves = 0
    print(
        f"API tree traversal started | shopId={shop_id} root={args.root_path or '<all>'} existing={len(existing)}",
        flush=True,
    )
    for category in iter_category_tree_leaves_by_api(page, shop_id=shop_id, root_path_text=args.root_path, limit=args.limit):
        seen_leaves += 1
        path_text = str(category.get("categoryPathText") or "").strip()
        category_id = str(category.get("categoryId") or "").strip()
        if not path_text or not category_id:
            continue
        if path_text in existing:
            skipped += 1
            if verbose and (skipped == 1 or skipped % 100 == 0):
                print(f"skip existing | skipped={skipped} current={path_text}", flush=True)
            continue
        if verbose:
            print(f"[{seen_leaves}] collect category: {path_text} | categoryId={category_id}", flush=True)
        try:
            attrs = fetch_category_attrs_by_api(page, category_id=category_id, shop_id=shop_id)
            upsert_category_attrs(conn, site=args.site, path_text=path_text, attrs=attrs, source_url=page.url, category=category)
            conn.commit()
            existing.add(path_text)
            item = {
                "category": path_text,
                "categoryId": category_id,
                "attrCount": len(attrs),
                "requiredCount": sum(1 for attr in attrs if attr.get("required")),
                "choiceFieldCount": sum(1 for attr in attrs if attr.get("options")),
            }
            collected.append(item)
            if verbose or len(collected) % 100 == 0:
                print(
                    f"progress | seen={seen_leaves} collected={len(collected)} errors={len(errors)} skipped={skipped}",
                    flush=True,
                )
        except Exception as exc:
            error_text = str(exc)
            if "不支持发品" in error_text:
                upsert_category_attrs(
                    conn,
                    site=args.site,
                    path_text=path_text,
                    attrs=[],
                    source_url=page.url,
                    category=category,
                    collection_status="unsupported",
                    collection_error=error_text,
                )
                conn.commit()
                existing.add(path_text)
                skipped += 1
                if verbose:
                    print(f"  unsupported category recorded | categoryId={category_id}", flush=True)
                continue
            errors.append({"category": path_text, "categoryId": category_id, "error": error_text})
            print(f"  ERROR {exc}", flush=True)
            time.sleep(0.3)
    return {
        "collected": collected,
        "errors": errors,
        "skipped": skipped,
        "shopId": shop_id,
        "categoryCount": seen_leaves,
    }


def collect_cached_categories_by_api(page: Any, conn: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    shop_id, categories = read_cached_categories(page, root_path_text=args.root_path, limit=args.limit)
    if not shop_id:
        raise RuntimeError("没有从页面状态读取到 shopId，不能调用 attributeList 接口")
    existing = existing_category_paths(conn, site=args.site) if args.skip_existing else set()
    collected: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    skipped = 0
    print(f"API 类目缓存读取完成 | shopId={shop_id} categories={len(categories)} existing={len(existing)}", flush=True)
    for index, category in enumerate(categories, start=1):
        path_text = str(category.get("categoryPathText") or "").strip()
        category_id = str(category.get("categoryId") or "").strip()
        if path_text in existing:
            skipped += 1
            if skipped == 1 or skipped % 100 == 0:
                print(f"跳过已采集 | skipped={skipped} current={path_text}", flush=True)
            continue
        print(f"[{index}/{len(categories)}] API采集类目: {path_text} | categoryId={category_id}", flush=True)
        try:
            attrs = fetch_category_attrs_by_api(page, category_id=category_id, shop_id=shop_id)
            upsert_category_attrs(conn, site=args.site, path_text=path_text, attrs=attrs, source_url=page.url, category=category)
            conn.commit()
            existing.add(path_text)
            item = {
                "category": path_text,
                "categoryId": category_id,
                "attrCount": len(attrs),
                "requiredCount": sum(1 for attr in attrs if attr.get("required")),
                "choiceFieldCount": sum(1 for attr in attrs if attr.get("options")),
            }
            collected.append(item)
            print(
                f"  OK 属性={item['attrCount']} 必填={item['requiredCount']} 候选字段={item['choiceFieldCount']} 累计={len(collected)} 失败={len(errors)}",
                flush=True,
            )
        except Exception as exc:
            errors.append({"category": path_text, "categoryId": category_id, "error": str(exc)})
            print(f"  ERROR {exc}", flush=True)
            time.sleep(0.3)
    return {"collected": collected, "errors": errors, "skipped": skipped, "shopId": shop_id, "categoryCount": len(categories)}


def collect_paths_for_args(page: Any, mode: str, limit: int, root_path_text: str = "") -> list[list[str]]:
    if mode == "descendants":
        root_path = split_category_path(root_path_text)
        if not root_path:
            state = open_category_modal(page)
            active = active_path_from_state(state)
            if not active:
                return []
            root_path = [active[0]]
        return collect_descendant_leaf_paths(page, root_path, limit)
    if mode == "all":
        return collect_descendant_leaf_paths(page, [], limit)
    return collect_paths(page, mode, limit)


def iter_paths_for_args(page: Any, mode: str, limit: int, root_path_text: str = ""):
    if mode == "descendants":
        root_path = split_category_path(root_path_text)
        if not root_path:
            state = open_category_modal(page)
            active = active_path_from_state(state)
            if not active:
                return
            root_path = [active[0]]
        yield from iter_descendant_leaf_paths(page, root_path, limit)
        return
    if mode == "all":
        yield from iter_descendant_leaf_paths(page, [], limit)
        return
    for path in collect_paths(page, mode, limit):
        yield path


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Collect Dianxiaomi Temu category attributes into local SQLite.")
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    parser.add_argument("--database-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--site", default="美国站")
    parser.add_argument("--mode", choices=["current", "current-branch", "descendants", "all", "api-cache", "api-tree"], default="current-branch")
    parser.add_argument("--root-path", default="", help="mode=descendants 时使用，例如：服装、鞋靴和珠宝饰品 > 女童时尚 > 女童饰品")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--quiet", action="store_true", help="Reduce per-category output during long API tree crawls.")
    parser.add_argument("--skip-existing", action="store_true", help="跳过本地库中已存在的类目，适合断点续采")
    args = parser.parse_args()

    db_path = Path(args.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(args.cdp_url)
        page = find_edit_page(browser)
        page.bring_to_front()

        if args.mode in {"api-cache", "api-tree"}:
            with sqlite3.connect(db_path) as conn:
                ensure_schema(conn)
                if args.mode == "api-tree":
                    result = collect_category_tree_by_api(page, conn, args)
                else:
                    result = collect_cached_categories_by_api(page, conn, args)
            summary = {
                "ok": not result["errors"],
                "mode": args.mode,
                "database": str(db_path),
                "shopId": result["shopId"],
                "categoryCount": result["categoryCount"],
                "collected": len(result["collected"]),
                "skipped": result["skipped"],
                "errors": result["errors"],
                "items": result["collected"],
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
            return

        collected: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        skipped = 0
        visited = 0
        with sqlite3.connect(db_path) as conn:
            ensure_schema(conn)
            existing = existing_category_paths(conn, site=args.site) if args.skip_existing else set()
            if existing:
                print(f"本地已有类目 {len(existing)} 个，将边遍历边跳过", flush=True)
            for path in iter_paths_for_args(page, args.mode, args.limit, args.root_path):
                path_text = " > ".join(path)
                if not path_text:
                    continue
                if path_text in existing:
                    skipped += 1
                    if skipped == 1 or skipped % 50 == 0:
                        print(f"已跳过本地已有类目 {skipped} 个，当前={path_text}", flush=True)
                    continue
                visited += 1
                print(f"[{visited}] 采集类目: {path_text}", flush=True)
                try:
                    navigate_modal_path(page, path)
                    click_modal_choose(page)
                    wait_category_text(page, path_text)
                    scan = scan_product_attrs(page)
                    actual_path = str(scan.get("categoryText") or path_text).strip() or path_text
                    attrs = scan.get("fields") if isinstance(scan.get("fields"), list) else []
                    upsert_category_attrs(conn, site=args.site, path_text=actual_path, attrs=attrs, source_url=page.url)
                    conn.commit()
                    existing.add(actual_path)
                    collected.append({"category": actual_path, "attrCount": len(attrs), "requiredCount": sum(1 for item in attrs if item.get("required"))})
                    print(f"  OK 属性={len(attrs)} 必填={collected[-1]['requiredCount']} 累计={len(collected)} 失败={len(errors)} 跳过={skipped}", flush=True)
                except Exception as exc:
                    error = {"category": path_text, "error": str(exc)}
                    errors.append(error)
                    print(f"  ERROR {exc}", flush=True)
                    try:
                        page.keyboard.press("Escape")
                    except Exception:
                        pass
                    time.sleep(0.5)
        if visited == 0 and skipped == 0:
            raise RuntimeError("没有读取到可采集类目路径")
        summary = {
            "ok": not errors,
            "mode": args.mode,
            "database": str(db_path),
            "collected": len(collected),
            "skipped": skipped,
            "errors": errors,
            "items": collected,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
