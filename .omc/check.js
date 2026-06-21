        const API_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
            ? 'http://127.0.0.1:8001' : '';

        const NPC_NAMES = {linwaner: '林婉儿', chenhao: '陈浩', old_yang: '杨老'};
        const SCENE_NAMES = {outer_gate: '外门', inner_gate: '内门', bamboo_forest: '竹林', market: '集市', mountain_range: '山脉'};

        let worldScenes = [];  // [{id,name,connections,atmosphere}] from /game/scenes
        async function loadWorldScenes() {
            try {
                const res = await fetch(`${API_URL}/game/scenes`);
                const data = await res.json();
                worldScenes = data.scenes || [];
            } catch (e) { console.error('scenes load failed', e); }
        }

        // Display-only maps for NPC richness (no English ids leak to the player).
        const NPC_ROLE = {linwaner: '师姐', chenhao: '师兄', old_yang: '守门人'};
        const NPC_HINT = {linwaner: '知心师姐，似有心事', chenhao: '豪爽师兄，常在集市', old_yang: '守门老人，深藏不露'};
        // 时辰 table — mirror of engine.models.SHICHEN_LABELS (keep in sync).
        const SHICHEN = ['子时·夜半','丑时·鸡鸣','寅时·平旦','卯时·日出','辰时·晨光初照','巳时·隅中','午时·日中','未时·日昳','申时·晡时','酉时·日入','戌时·黄昏','亥时·人定'];
        function shichenLabel(tick) { return SHICHEN[(tick || 0) % 12]; }

        // Cached panel data, refreshed by updateStatus() and after each action.
        let panelData = {scene:null, npcs:[], quests:[], nextQuest:null, player:null};

        // Panel clicks PREFILL the input (focus optional) — never auto-send, so
        // every action still flows through classify→engine→world→dm.
        function prefill(text, focus) {
            const el = document.getElementById('user-input');
            el.value = text;
            if (focus !== false) el.focus();
        }

        let currentDrawer = null;
        function openDrawer(which) {
            currentDrawer = which;
            document.getElementById('drawer-overlay').style.display = 'block';
            document.getElementById('drawer').style.display = 'block';
            ['chip-role','chip-map'].forEach(id => document.getElementById(id).classList.remove('on'));
            document.getElementById('chip-' + which).classList.add('on');
            const titles = {role:'角色 · 所务与人物', map:'地图'};
            document.getElementById('drawer-title').textContent = titles[which];
            renderDrawer(which);
        }
        function closeDrawer() {
            currentDrawer = null;
            document.getElementById('drawer-overlay').style.display = 'none';
            document.getElementById('drawer').style.display = 'none';
            ['chip-role','chip-map'].forEach(id => document.getElementById(id).classList.remove('on'));
        }
        function renderDrawer(which) {
            const body = document.getElementById('drawer-body');
            if (which === 'role') body.innerHTML = renderRolePanel();
            else if (which === 'map') body.innerHTML = renderMapPanel();
        }
        // The current scene panel is always visible — it's the base for
        // interaction. Reuses renderPlacePanel() so the persistent panel and
        // the (now-removed) 地点 drawer stay in sync. Tags use data-prefill
        // so the global delegated handler fills the input without auto-sending.
        function renderScenePanel() {
            const panel = document.getElementById('scene-panel');
            if (!panel) return;
            panel.innerHTML = renderPlacePanel();
        }
        // Panel renderers are added in Tasks 10-12; stubs so the shell works.
        function renderRolePanel() {
            const p = panelData.player || {};
            const quests = panelData.quests || [];
            const npcs = panelData.npcs || [];
            const scene = panelData.scene || {};
            const presentIds = new Set((scene.npcs_present) || []);
            const nextT = p.next_threshold;
            const spPct = nextT ? Math.min(100, Math.round((p.spirit_power||0)/nextT*100)) : 100;
            const hpPct = p.max_hp ? Math.round((p.hp||0)/p.max_hp*100) : 100;

            let html = '<div class="panel-sec"><div class="panel-label">所务 · 随缘而启</div>';
            quests.forEach(q => {
                const cls = q.status === 'completed' ? 'qrow done' : 'qrow now';
                const tag = q.status === 'completed' ? '将隐去' : '进行中';
                html += `<div class="${cls}"><div class="qbox"></div><div class="qtxt">${escapeHtml(q.label)}</div><div class="qtag">${tag}</div></div>`;
            });
            if (panelData.nextQuest) {
                html += `<div style="font-size:11px;color:#8a7aa8;padding:2px 4px">（将解锁：${escapeHtml(panelData.nextQuest.label)}…）</div>`;
            }
            html += '</div>';

            html += `<div class="panel-sec"><div class="panel-label">${escapeHtml(p.name||'')} · ${escapeHtml(p.affinity||'')}灵根</div>`;
            html += `<div class="stat-line"><span>境界</span><b>${escapeHtml(p.level||'')}</b></div>`;
            html += `<div class="panel-label">灵力</div><div class="bar sp"><i style="width:${spPct}%"></i></div>`;
            html += `<div class="bar-pct">${p.spirit_power??0}${nextT? ' / '+nextT+' 至下境':''}</div>`;
            html += `<div class="panel-label">气血</div><div class="bar hp"><i style="width:${hpPct}%"></i></div>`;
            html += `<div class="bar-pct">${p.hp??0} / ${p.max_hp??0}</div>`;
            html += `<div class="stat-line"><span>时辰</span><b>${shichenLabel(p.tick)}</b></div>`;
            html += `<div class="panel-label">行囊</div><div>`;
            (p.inventory||[]).forEach(it => {
                html += `<span class="obj-tag" data-prefill="查看${escapeAttr(it)}">${escapeHtml(it)}</span>`;
            });
            if (!(p.inventory||[]).length) html += '<span style="color:#8a7aa8;font-size:12px">空空如也</span>';
            html += `</div><div style="margin-top:8px"><span class="obj-tag" data-prefill="修炼">打坐修炼</span></div>`;
            html += '</div>';

            // 在场人物
            const present = npcs.filter(n => n.present);
            const absent = npcs.filter(n => !n.present);
            html += '<div class="panel-sec"><div class="panel-label">在场人物</div>';
            if (present.length) present.forEach(n => html += npcCard(n, false));
            else html += '<div style="color:#8a7aa8;font-size:12px">四下无人</div>';
            if (absent.length) {
                html += '<div class="panel-label">不在场</div>';
                absent.forEach(n => html += npcCard(n, true));
            }
            html += '</div>';
            return html;
        }

        function npcCard(n, absent) {
            const name = NPC_NAMES[n.id] || n.id;
            const role = NPC_ROLE[n.id] || '';
            const hint = NPC_HINT[n.id] || '';
            const cls = 'npc-card' + (absent ? ' absent' : '');
            let acts = '';
            if (!absent) {
                acts = `<div class="npc-acts">`
                    + `<span class="npc-btn go" data-prefill="和${escapeAttr(name)}搭话">搭话</span>`
                    + `<span class="npc-btn go" data-prefill="对${escapeAttr(name)}说：" data-focus="1">自由聊天</span>`
                    + `<span class="npc-btn dim">切磋</span>`
                    + `</div>`;
            }
            const loc = absent ? `常驻 ${SCENE_NAMES[n.default_scene]||n.default_scene}` : hint;
            return `<div class="${cls}">`
                + `<div class="npc-head"><b>${escapeHtml(name)} · ${escapeHtml(role)}</b><span class="npc-fav">${escapeHtml(n.relationship_stage||'陌生')} · ${n.favorability??0}</span></div>`
                + `<div class="npc-desc">${escapeHtml(loc)}</div>`
                + acts + `</div>`;
        }
        function renderPlacePanel() {
            const scene = panelData.scene || {};
            const desc = scene.description || '';
            const landmarks = scene.landmarks || [];
            const conns = scene.connections || [];
            // Turn landmark occurrences in the description into clickable links.
            let descHtml = escapeHtml(desc);
            landmarks.forEach(lm => {
                if (lm && descHtml.includes(escapeHtml(lm))) {
                    descHtml = descHtml.split(escapeHtml(lm)).join(
                        `<span class="link-obj" data-prefill="查看${escapeAttr(lm)}">${escapeHtml(lm)}</span>`);
                }
            });
            let html = `<div class="panel-sec"><div class="panel-label">${escapeHtml(scene.name||'')} · ${escapeHtml(scene.atmosphere||'')}</div>`;
            html += `<div class="scene-desc">${descHtml}</div></div>`;

            // 在场人物 — present NPCs as interactable "搭话" tags, listed
            // right after the scene description so people are the first
            // interaction affordance in the persistent scene panel.
            const presentNpcs = (panelData.npcs || []).filter(n => n.present);
            html += '<div class="panel-sec"><div class="panel-label">在场人物</div>';
            if (presentNpcs.length) {
                presentNpcs.forEach(n => {
                    const name = NPC_NAMES[n.id] || n.id;
                    const role = NPC_ROLE[n.id] || '';
                    const label = role ? `${escapeHtml(name)} · ${escapeHtml(role)}` : escapeHtml(name);
                    html += `<span class="who-tag" data-prefill="和${escapeAttr(name)}搭话">${label} · 搭话</span>`;
                });
            } else {
                html += '<span style="color:#8a7aa8;font-size:12px">四下无人</span>';
            }
            html += '</div>';

            html += '<div class="panel-sec"><div class="panel-label">可交互物件</div>';
            landmarks.forEach(lm => {
                html += `<span class="obj-tag" data-prefill="查看${escapeAttr(lm)}">${escapeHtml(lm)} · 查看</span>`;
            });
            if (!landmarks.length) html += '<span style="color:#8a7aa8;font-size:12px">无可交互物件</span>';
            html += '</div>';

            html += '<div class="panel-sec"><div class="panel-label">可前往</div>';
            conns.forEach(cid => {
                html += `<span class="move-tag" data-prefill="去${escapeAttr(SCENE_NAMES[cid]||cid)}">→ ${escapeHtml(SCENE_NAMES[cid]||cid)}</span>`;
            });
            if (!conns.length) html += '<span style="color:#8a7aa8;font-size:12px">无路可去</span>';
            html += '</div>';

            if (lastWorldEvent && lastWorldEvent.name) {
                html += `<div class="panel-sec"><div class="panel-label">当前异象</div>`
                     + `<div class="scene-desc" style="color:#9dd5ff">◈ ${escapeHtml(lastWorldEvent.name)}</div></div>`;
            }
            return html;
        }
        function renderMapPanel() {
            const current = (panelData.scene && panelData.scene.id) || (panelData.player && panelData.player.current_scene);
            // Reachable = scenes directly connected to the current scene.
            // Prefer panelData.scene.connections (always present) over
            // worldScenes so the map still works if /game/scenes hasn't
            // loaded yet.
            const conns = (panelData.scene && panelData.scene.connections) || [];
            const reachable = new Set(conns);

            // Fixed 2D layout reflecting scene adjacency:
            //        集市
            //         |
            //   外门 — 内门 — 竹林 — 山脉
            const NODES = [
                {id: 'market',         x: 50,  y: 36,  icon: '集', name: '修士集市'},
                {id: 'outer_gate',     x: 50,  y: 110, icon: '门', name: '青云门外门'},
                {id: 'inner_gate',     x: 150, y: 110, icon: '阁', name: '青云门内门'},
                {id: 'bamboo_forest',  x: 250, y: 110, icon: '竹', name: '幽竹林'},
                {id: 'mountain_range', x: 350, y: 110, icon: '山', name: '妖兽山脉'},
            ];
            const byId = {};
            NODES.forEach(n => byId[n.id] = n);
            // Undirected edges (drawn once each).
            const EDGES = [
                ['market', 'outer_gate'],
                ['outer_gate', 'inner_gate'],
                ['inner_gate', 'bamboo_forest'],
                ['bamboo_forest', 'mountain_range'],
            ];

            const W = 400, H = 168;
            let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet" style="display:block;max-height:42vh;margin:4px 0">`;

            // Edges first so nodes sit on top.
            EDGES.forEach(([a, b]) => {
                const A = byId[a], B = byId[b];
                if (!A || !B) return;
                svg += `<line x1="${A.x}" y1="${A.y}" x2="${B.x}" y2="${B.y}" stroke="#6b3fa0" stroke-width="2" opacity="0.55"/>`;
            });

            // Nodes. Draw the current scene last so it sits on top of edges.
            const ordered = NODES.slice().sort((a, b) => (a.id === current ? 1 : 0) - (b.id === current ? 1 : 0));
            ordered.forEach(n => {
                const here = n.id === current;
                const reach = reachable.has(n.id);
                let stroke = '#7b5ea7', fill = 'rgba(255,255,255,0.05)', opacity = 1, cursor = '', labelColor = '#b8a0d4', tag = '';
                const dataAttr = (reach && !here) ? `data-prefill="去${escapeAttr(SCENE_NAMES[n.id] || n.id)}"` : '';
                if (here) {
                    stroke = '#9dd5ff'; fill = 'rgba(107,179,224,0.28)'; labelColor = '#9dd5ff'; tag = '你在此';
                } else if (reach) {
                    stroke = '#5a8a6a'; fill = 'rgba(90,138,106,0.20)'; labelColor = '#b8e6b8'; cursor = 'pointer'; tag = '前往';
                } else {
                    opacity = 0.4; tag = '远';
                }
                svg += `<g ${dataAttr} style="cursor:${cursor}" opacity="${opacity}">`;
                if (here) {
                    // subtle outer ring to mark the current location
                    svg += `<circle cx="${n.x}" cy="${n.y}" r="29" fill="none" stroke="#9dd5ff" stroke-width="1" opacity="0.5"/>`;
                }
                svg += `<circle cx="${n.x}" cy="${n.y}" r="23" fill="${fill}" stroke="${stroke}" stroke-width="${here?3:2}"/>`;
                svg += `<text x="${n.x}" y="${n.y+1}" text-anchor="middle" dominant-baseline="central" font-size="20" fill="#e8e0f5" style="pointer-events:none">${escapeHtml(n.icon)}</text>`;
                svg += `<text x="${n.x}" y="${n.y-32}" text-anchor="middle" font-size="9" fill="${labelColor}" style="pointer-events:none">${escapeHtml(tag)}</text>`;
                svg += `<text x="${n.x}" y="${n.y+40}" text-anchor="middle" font-size="10.5" fill="${here?'#9dd5ff':reach?'#b8e6b8':'#b8a0d4'}" style="pointer-events:none">${escapeHtml(n.name)}</text>`;
                svg += `</g>`;
            });
            svg += `</svg>`;

            let html = `<div class="panel-sec"><div class="panel-label">场景图谱（蓝=你在此 · 绿=可前往，点绿点即前往 · 暗=需经他处）</div>`;
            html += svg;
            // Current scene's landmarks, below the graph.
            if (panelData.scene && panelData.scene.landmarks && panelData.scene.landmarks.length) {
                html += `<div class="panel-label" style="margin-top:6px">所在场景地标</div><div style="font-size:12px;color:#b8a0d4">${panelData.scene.landmarks.map(escapeHtml).join(' · ')}</div>`;
            }
            html += '</div>';
            return html;
        }

        // The opening line is shown once, on first status load, and must match
        // the player's actual scene — never a hardcoded outer_gate string.
        let introShown = false;
        // Last shown 所务 label, so we only surface a "所务更新" line when it changes.
        let lastGoalLabel = null;
        let lastWorldEvent = null;

        async function updateStatus() {
            try {
                const res = await fetch(`${API_URL}/player/status`);
                const data = await res.json();
                // Cache panel fields before status-bar updates so the drawer has
                // fresh data even if it's open during a status refresh.
                panelData = {
                    scene: data.scene, npcs: data.npcs || [],
                    quests: data.quests || [],
                    nextQuest: data.next_quest || null,
                    player: data,  // level/spirit/hp/max_hp/affinity/inventory/tick/next_threshold
                };
                document.getElementById('p-loc').textContent = (data.scene && data.scene.name) || SCENE_NAMES[data.current_scene] || data.current_scene || '未知';
                document.getElementById('p-goal').textContent = (data.goal && data.goal.label) || '—';
                if (data.goal && data.goal.label) lastGoalLabel = data.goal.label;
                document.getElementById('p-level').textContent = data.level || '练气期一层';
                document.getElementById('p-spirit').textContent = data.spirit_power ?? 0;
                document.getElementById('p-hp').textContent = `${data.hp ?? 100}/${data.max_hp ?? 100}`;
                document.getElementById('p-atk').textContent = data.attack ?? 0;
                document.getElementById('p-def').textContent = data.defense ?? 0;

                // 在场人物 / 通道 live in the 地点 & 角色 panels — not duplicated
                // in the top status bar (keeps the bar one compact row).
                renderScenePanel();
                maybeShowIntro(data);
            } catch(e) {
                console.error('Status update failed:', e);
            }
        }

        function maybeShowIntro(data) {
            if (introShown) return;
            introShown = true;
            const scene = data.scene;
            const sceneName = (scene && scene.name) || SCENE_NAMES[data.current_scene] || data.current_scene || '青云门外门';
            const npcs = (scene && scene.npcs_present) || [];
            const conns = (scene && scene.connections) || [];
            // Hints reflect who is actually here and where the player can go.
            const hints = [];
            if (npcs.length) hints.push('和' + (NPC_NAMES[npcs[0]] || npcs[0]) + '说话');
            conns.slice(0, 2).forEach(c => hints.push('去' + (SCENE_NAMES[c] || c)));
            hints.push('修炼');
            const hintStr = `你想做什么？（试试：${hints.join('、')}）`;
            // Evocative cold-open only for a brand-new game at the outer gate;
            // otherwise a scene-aware line so the intro never contradicts reality.
            const prefix = (data.tick === 0 && data.current_scene === 'outer_gate')
                ? '【系统】你睁开眼，发现自己正躺在柴房的硬板床上。四周弥漫着霉味，窗外传来师兄们练剑的呼喊声。'
                : `【系统】你此刻身处${sceneName}，四下打量一番。`;
            const el = document.createElement('div');
            el.className = 'msg system';
            const bubble = document.createElement('div');
            bubble.className = 'bubble';
            bubble.textContent = prefix + hintStr;
            el.appendChild(bubble);
            const container = document.getElementById('chat-container');
            container.appendChild(el);
            container.scrollTop = container.scrollHeight;
        }

        function addBattleCard(container, combat) {
            const card = document.createElement('div');
            card.className = 'battle-card';
            const resultClass = combat.result === 'win' ? 'win'
                : combat.result === 'lose' ? 'lose'
                : combat.result === 'ongoing' ? 'ongoing' : 'flee';
            const resultText = combat.result === 'win' ? '胜'
                : combat.result === 'lose' ? '败'
                : combat.result === 'ongoing' ? '交战中' : '撤退';
            card.innerHTML = `
                <h3>⚔ ${combat.enemy}</h3>
                <div class="battle-row"><span>造成伤害</span><span>${combat.dmg_to_enemy}</span></div>
                <div class="battle-row"><span>受到伤害</span><span>${combat.dmg_to_player}</span></div>
                <div class="battle-row"><span>敌方剩余</span><span>${combat.enemy_remaining_hp} HP</span></div>
                <div class="battle-row"><span>我方剩余</span><span>${combat.player_remaining_hp} HP</span></div>
                <div class="battle-result ${resultClass}">${resultText}</div>
            `;
            container.appendChild(card);
        }

        function addBreakthroughMsg(container, bt) {
            const msg = document.createElement('div');
            msg.className = 'breakthrough-msg';
            msg.textContent = `🌟 突破！${bt.from} → ${bt.to} 🌟`;
            container.appendChild(msg);
        }

        function addWorldEvent(container, worldEvent) {
            if (!worldEvent) return;
            const el = document.createElement('div');
            el.className = 'world-event';
            const name = worldEvent.name || '';
            const text = name ? `◈ ${name}` : '◈ 世界事件';
            el.textContent = text;
            container.appendChild(el);
        }

        function addIntervention(container, intervention) {
            if (!intervention) return;
            const card = document.createElement('div');
            card.className = 'intervention-card';
            const desc = document.createElement('div');
            desc.className = 'intervention-desc';
            desc.textContent = intervention.description || '你可以选择：';
            card.appendChild(desc);
            const options = intervention.options || [];
            options.forEach(opt => {
                const btn = document.createElement('button');
                btn.className = 'intervention-btn';
                btn.textContent = opt;
                btn.addEventListener('click', () => {
                    document.getElementById('user-input').value = opt;
                    sendAction();
                });
                card.appendChild(btn);
            });
            container.appendChild(card);
        }

        function updateFavorability(npc) {
            if (!npc) return;
            document.getElementById('npc-rel').style.display = 'inline';
            document.getElementById('favorability-bar').style.display = 'block';
            document.getElementById('p-npc-stage').textContent = npc.relationship_stage || '陌生';
            document.getElementById('p-npc-fav').textContent = npc.favorability ?? 50;
            document.getElementById('favorability-fill').style.width = `${npc.favorability ?? 50}%`;
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function escapeAttr(s) {
            // For text embedded in an HTML attribute (e.g. inside onclick="...").
            // escapeHtml covers &<> for text content; attributes also need quotes
            // escaped so a value can't break out of the attribute or the JS string.
            return escapeHtml(s == null ? '' : String(s)).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
        }

        // Incrementally decode the `story` string value from the streaming
        // response JSON (which is sent as {"story":"<streamed>", ...rest}).
        // Mirrors dm/contract.extract_story_so_far so the client can render
        // the narrative live, before the full object arrives. A trailing
        // incomplete escape is withheld so we never show a half-decoded char.
        function extractStorySoFar(text) {
            const key = '"story"';
            const idx = text.indexOf(key);
            if (idx === -1) return '';
            let i = idx + key.length;
            const n = text.length;
            while (i < n && ' \t\n\r'.includes(text[i])) i++;
            if (i >= n || text[i] !== ':') return '';
            i++;
            while (i < n && ' \t\n\r'.includes(text[i])) i++;
            if (i >= n || text[i] !== '"') return '';
            i++; // past opening quote
            let out = '';
            while (i < n) {
                const c = text[i];
                if (c === '\\') {
                    if (i + 1 >= n) break; // incomplete escape — withhold
                    const nxt = text[i + 1];
                    if (nxt === '"') { out += '"'; i += 2; }
                    else if (nxt === '\\') { out += '\\'; i += 2; }
                    else if (nxt === '/') { out += '/'; i += 2; }
                    else if (nxt === 'n') { out += '\n'; i += 2; }
                    else if (nxt === 't') { out += '\t'; i += 2; }
                    else if (nxt === 'r') { out += '\r'; i += 2; }
                    else if (nxt === 'b') { out += '\b'; i += 2; }
                    else if (nxt === 'f') { out += '\f'; i += 2; }
                    else if (nxt === 'u') {
                        if (i + 6 > n) break; // incomplete \uXXXX — withhold
                        const hex = text.substring(i + 2, i + 6);
                        if (!/^[0-9a-fA-F]{4}$/.test(hex)) { i += 2; continue; }
                        out += String.fromCharCode(parseInt(hex, 16));
                        i += 6;
                    } else { out += nxt; i += 2; }
                } else if (c === '"') {
                    break; // closing quote — story complete
                } else {
                    out += c;
                    i++;
                }
            }
            return out;
        }

        async function sendAction() {
            const inputEl = document.getElementById('user-input');
            const text = inputEl.value.trim();
            if (!text) return;
            inputEl.value = '';

            const container = document.getElementById('chat-container');

            // User message
            const userMsg = document.createElement('div');
            userMsg.className = 'msg user';
            userMsg.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
            container.appendChild(userMsg);

            // AI response placeholder
            const aiMsgEl = document.createElement('div');
            aiMsgEl.className = 'msg system';
            const aiBubbleEl = document.createElement('div');
            aiBubbleEl.className = 'bubble';
            aiBubbleEl.innerText = '正在思考...';
            aiMsgEl.appendChild(aiBubbleEl);
            container.appendChild(aiMsgEl);
            container.scrollTop = container.scrollHeight;

            try {
                const response = await fetch(`${API_URL}/game/action`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_input: text })
                });

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let fullText = "";

                while (true) {
                    const { value, done } = await reader.read();
                    if (done) break;
                    fullText += decoder.decode(value, { stream: true });
                    // The backend streams {"story":"<text>", ...}. Show the
                    // narrative live as it arrives; keep the placeholder until
                    // the story field starts.
                    const liveStory = extractStorySoFar(fullText);
                    aiBubbleEl.innerText = liveStory || '正在思考...';
                    container.scrollTop = container.scrollHeight;
                }

                // Try to parse JSON response
                try {
                    let cleanJson = fullText.replace(/```json/g, '').replace(/```/g, '').trim();
                    const result = JSON.parse(cleanJson);

                    // Show story text (fallback if empty)
                    aiBubbleEl.innerText = result.story || '（你的行动似乎没有引起什么变化……）';

                    // Show battle card if combat
                    if (result.combat) {
                        addBattleCard(container, result.combat);
                    }

                    // Show breakthrough if present
                    if (result.breakthrough) {
                        addBreakthroughMsg(container, result.breakthrough);
                    }

                    // Show world event if present
                    if (result.world_event) {
                        addWorldEvent(container, result.world_event);
                        lastWorldEvent = result.world_event;
                    }

                    // Show intervention options if present
                    if (result.intervention) {
                        addIntervention(container, result.intervention);
                    }

                    // Surface a 所务 (objective) update line when the goal advances.
                    if (result.goal && result.goal.label && result.goal.label !== lastGoalLabel) {
                        const goalEl = document.createElement('div');
                        goalEl.className = 'msg system';
                        const goalBubble = document.createElement('div');
                        goalBubble.className = 'bubble';
                        goalBubble.textContent = `【所务】${result.goal.label}`;
                        goalEl.appendChild(goalBubble);
                        container.appendChild(goalEl);
                        lastGoalLabel = result.goal.label;
                    }

                    // Update favorability if NPC data present
                    if (result.npc) {
                        updateFavorability(result.npc);
                    }

                    // Refresh panel cache from the action response so an open
                    // drawer updates live without waiting for status re-fetch.
                    // Action response nests player stats under result.player
                    // (name/current_scene/tick/level/spirit_power/hp/max_hp/
                    // attack/defense) but omits affinity/inventory/next_threshold,
                    // so those fall back to the cached panelData.player values.
                    panelData = {
                        scene: result.scene || panelData.scene,
                        npcs: result.npcs || panelData.npcs,
                        quests: result.quests || panelData.quests,
                        nextQuest: result.next_quest || null,
                        player: Object.assign({}, panelData.player, result.player || {}, {
                            // keep next_threshold from last status; action resp lacks it
                            next_threshold: panelData.player && panelData.player.next_threshold,
                        }),
                    };
                    if (currentDrawer) renderDrawer(currentDrawer);
                    renderScenePanel();

                    // Update status bar
                    await updateStatus();

                } catch(e) {
                    // Fallback: show raw text
                    console.log('JSON parse failed, showing raw text', e);
                }

            } catch (err) {
                aiBubbleEl.innerText = '【系统】传信飞鸽在半路被雷劈了，请重试。';
            }
        }

        // Handle Enter key
        document.getElementById('user-input').addEventListener('keydown', function(e) {
            if (e.key === 'Enter') sendAction();
        });

        // Delegated handler for panel prefill clicks. Panel HTML uses
        // data-prefill="..." (attribute-escaped via escapeAttr) instead of inline
        // onclick, so a prefill value containing a quote can't break out of a
        // nested JS string. data-focus="1" requests input focus.
        document.addEventListener('click', function(e) {
            const el = e.target.closest('[data-prefill]');
            if (!el) return;
            prefill(el.getAttribute('data-prefill') || '',
                    el.getAttribute('data-focus') === '1');
            // Close the drawer so the prefilled input is visible and ready to
            // send — otherwise the drawer (z-index 21) covers the input bar
            // and the click looks like it did nothing.
            if (currentDrawer) closeDrawer();
        });

        // Initial status load
        loadWorldScenes();
        updateStatus();
