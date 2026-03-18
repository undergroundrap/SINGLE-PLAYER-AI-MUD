"use client";
import { useState, useEffect, useRef } from 'react';

interface LogEntry {
  text: string;
  type: 'system' | 'player' | 'hint' | 'combat' | 'error';
  id?: string; // used by description slots so they can be filled in-place
}

const RACES = ["Human", "Orc", "Dwarf", "Elf", "Undead", "Goblin", "Gnome", "Troll"];
const CLASSES = ["Warrior", "Paladin", "Hunter", "Rogue", "Priest", "Shaman", "Mage", "Warlock", "Druid"];

const RACE_FLAVOR: Record<string, string> = {
  "Human": "Versatile and ambitious, the people of the Seven Realms are known for their resilience and spirit.",
  "Orc": "Noble warriors from the Ancestral Realm, they value honor and strength above all.",
  "Dwarf": "Ancient masters of stone and forge, they are as sturdy as the mountains they inhabit.",
  "Elf": "Mysterious and ancient, they are protectors of nature and masters of the magic.",
  "Undead": "Bound by death but freed from the shadows, they seek their own path in a world that fears them.",
  "Goblin": "Cunning and inventive, these small creatures use their wits to thrive in a world of giants.",
  "Gnome": "Brilliant and eccentric, they provide the realms with unmatched technological ingenuity.",
  "Troll": "Cunning and agile, they use primal instincts and ancient spirits to survive."
};

const CLASS_FLAVOR: Record<string, string> = {
  "Warrior": "A master of plate and steel, standing on the frontlines to protect their allies.",
  "Paladin": "A holy crusader who wields the Light to smite evil and mend wounds.",
  "Hunter": "A tracker and marksman who fights alongside a loyal beast companion.",
  "Rogue": "A shadow-dweller who uses stealth and poisons to strike with lethal precision.",
  "Priest": "A spiritual guide who balances powerful healing with shadow magic.",
  "Shaman": "A conduit of the elements, calling upon fire, frost, and earth.",
  "Mage": "A weaver of arcane energies, capable of incinerating foes from a distance.",
  "Warlock": "A seeker of dark knowledge who commands demons and drains life.",
  "Druid": "A keeper of the wild who can shapeshift into primal forms."
};

// Returns the new progress value if this quest is tracked by the kill, otherwise null.
const GATHER_SUFFIX_RE = / (trophy|tusk|fang|pelt|wing|tail|hide|scale|stinger|ear|bone|finger|claw|horn|core|essence|shard|crystal|badge)$/i;
function questNewProgress(q: any, targetName: string, targetIsNamed: boolean, targetIsElite?: boolean): number | null {
  // targetName must CONTAIN the quest target (e.g. "Veteran Cave Bat" contains "Cave Bat")
  // NOT the reverse — otherwise killing "Bat" would wrongly credit a "Cave Bat" quest
  const mob = targetName.toLowerCase().includes(q.target_id.toLowerCase());
  const gatherBase = q.quest_type === 'gather'
    ? q.target_id.toLowerCase().replace(GATHER_SUFFIX_RE, '').trim()
    : null;
  const tracked = (q.quest_type === 'kill' && mob)
               || (q.quest_type === 'hunt' && (targetIsNamed || !!targetIsElite))
               || (q.quest_type === 'gather' && !!gatherBase && targetName.toLowerCase().includes(gatherBase));
  return tracked ? Math.min(q.target_count, q.current_progress + 1) : null;
}

export default function Home() {
  const [player, setPlayer] = useState<any>(null);
  const [playerId, setPlayerId] = useState<string | null>(null);
  const [zone, setZone] = useState<any>(null);
  const [step, setStep] = useState<'intro' | 'load' | 'race' | 'class' | 'gender' | 'name' | 'game'>('intro');
  const [savedPlayers, setSavedPlayers] = useState<any[]>([]);
  const [creationData, setCreationData] = useState({ name: "", race: "", charClass: "", pronouns: "" });
  const [biography, setBiography] = useState<string>("");
  const [revealedNpcs, setRevealedNpcs] = useState<Set<string>>(new Set());
  const [logs, setLogs] = useState<LogEntry[]>([
    { text: "SINGLE PLAYER AI MUD", type: "system" },
    { text: "Welcome, traveler. A new destiny awaits.", type: "system" },
    { text: "Press 'Enter' to begin character creation.", type: "hint" }
  ]);
  const [input, setInput] = useState<string>("");
  const [worldInput, setWorldInput] = useState<string>("");
  const [target, setTarget] = useState<any>(null);
  const [targetDescription, setTargetDescription] = useState<string>('');
  const [combatFlash, setCombatFlash] = useState<boolean>(false);
  const [activeLoot, setActiveLoot] = useState<any>(null);
  const [isTalking, setIsTalking] = useState<boolean>(false);
  const [globalChat, setGlobalChat] = useState<{ name: string, text: string }[]>([]);
  const [chatSummary, setChatSummary] = useState<string>("");
  const [exploredLocations, setExploredLocations] = useState<Set<string>>(new Set());
  const [hoveredItem, setHoveredItem] = useState<any>(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  // Combat systems
  const [autoAttackTarget, setAutoAttackTarget] = useState<string | null>(null);
  const [attackCooldown, setAttackCooldown] = useState<number>(0);   // 0–100 %
  const [isAttacking, setIsAttacking] = useState<boolean>(false);
  const [lastCombatTime, setLastCombatTime] = useState<number>(0);
  // Consumable system
  const [healCd, setHealCd] = useState<number>(0);    // seconds remaining on heal cooldown
  const [xpCd, setXpCd] = useState<number>(0);        // seconds remaining on elixir cooldown
  const [activeXpBuff, setActiveXpBuff] = useState<{ bonus_pct: number; charges: number } | null>(null);
  // Rested XP
  const [restedXp, setRestedXp] = useState<number>(0);
  const [restedXpCap, setRestedXpCap] = useState<number>(0);
  // Gather (forage quests)
  const [gatherCooldown, setGatherCooldown] = useState<number>(0); // 0–100 % — used only for text label
  const [isGathering, setIsGathering] = useState<boolean>(false);
  const gatherBarRef = useRef<HTMLDivElement>(null); // driven directly by rAF for smooth animation
  // Dungeon
  const [dungeonRun, setDungeonRun] = useState<any>(null);
  const [dungeonAttacking, setDungeonAttacking] = useState<boolean>(false);
  const [gearScore, setGearScore] = useState<number>(0);
  // null → idle | 'choose' → pick what to delete | 'single' → confirm this char | 'all' → confirm wipe all
  const [resetConfirm, setResetConfirm] = useState<null | 'choose' | 'single' | 'all'>(null);
  const autoAttackRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const seenEntities = useRef<Set<string>>(new Set());
  const entityDescCache = useRef<Map<string, string>>(new Map());
  const seenWorldMessages = useRef<Set<string>>(new Set());
  const isInCombatRef = useRef(false); // kept in sync with autoAttackTarget
  const idleChatAbortRef = useRef<AbortController | null>(null); // aborted on mob kill to free LM Studio
  const chatMsgCountRef = useRef(0);
  const idleChatRef = useRef<{ zone: any; player: any; globalChat: any[] }>({ zone: null, player: null, globalChat: [] });
  const lastRegenSyncRef = useRef<number>(0); // timestamp of last HP sync to backend

  const ATTACK_COOLDOWN_MS = 1600; // slightly above backend 1.5s to avoid false cooldown hits

  useEffect(() => {
    // Small timeout to allow DOM reconciliation before scrolling
    const timer = setTimeout(() => {
      if (scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    }, 50);
    return () => clearTimeout(timer);
  }, [logs]);

  useEffect(() => {
    const handleGlobalMouseMove = (e: MouseEvent) => {
      setMousePos({ x: e.clientX, y: e.clientY });
    };
    window.addEventListener('mousemove', handleGlobalMouseMove);
    return () => window.removeEventListener('mousemove', handleGlobalMouseMove);
  }, []);

  // Re-focus the command input whenever the step changes
  useEffect(() => {
    const t = setTimeout(() => inputRef.current?.focus(), 80);
    return () => clearTimeout(t);
  }, [step]);

  // Redirect any keypress back to the input if something else stole focus
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const active = document.activeElement;
      if (active === inputRef.current) return;
      if (active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement) return;
      // Only redirect printable keys (ignore modifier-only, F-keys, etc.)
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // ── Patrol encounter timer ──────────────────────────────────────────────
  // Every 45s, ask the backend if a wandering enemy has appeared.
  // Backend owns all location/hub/mob checks — no stale zone/player state here.
  useEffect(() => {
    if (!playerId || step !== 'game' || dungeonRun) return;
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`http://localhost:8000/action/patrol_check/${playerId}`, { method: 'POST' });
        const data = await res.json();
        if (data.patrol) {
          addLog(`⚠ A ${data.mob_name} (Lv ${data.mob_level}) crosses your path!`, "combat");
          // Refresh zone using zone_id returned by backend (avoids stale player closure)
          if (data.zone_id) {
            const zRes = await fetch(`http://localhost:8000/zone/${data.zone_id}`);
            if (zRes.ok) setZone(await zRes.json());
          }
        }
      } catch { /* silent — patrol check is best-effort */ }
    }, 45000);
    return () => clearInterval(interval);
  }, [playerId, step, dungeonRun]);

  // Poll zone every 10s so the action bar always reflects live mob state
  // (patrol spawns, sim-player kills, respawns, etc.)
  useEffect(() => {
    if (!playerId || step !== 'game' || dungeonRun) return;
    const interval = setInterval(async () => {
      try {
        const pRes = await fetch(`http://localhost:8000/player/${playerId}`);
        if (!pRes.ok) return;
        const pData = await pRes.json();
        if (!pData.current_zone_id) return;
        const zRes = await fetch(`http://localhost:8000/zone/${pData.current_zone_id}`);
        if (zRes.ok) setZone(await zRes.json());
      } catch { /* silent */ }
    }, 10000);
    return () => clearInterval(interval);
  }, [playerId, step, dungeonRun]);

  // ── Auto-attack loop ────────────────────────────────────────────────────
  // Fires another attack tick automatically after the cooldown expires,
  // keeping combat flowing without spamming the button each hit.
  useEffect(() => {
    if (!autoAttackTarget || !playerId || step !== 'game') return;
    if (isAttacking) return; // already mid-request

    const fire = () => {
      executeCommand(`attack ${autoAttackTarget}`);
    };

    autoAttackRef.current = setTimeout(fire, ATTACK_COOLDOWN_MS);
    return () => {
      if (autoAttackRef.current) clearTimeout(autoAttackRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoAttackTarget, isAttacking]);

  // ── Cooldown progress bar animation ────────────────────────────────────
  useEffect(() => {
    if (!isAttacking) { setAttackCooldown(0); return; }
    setAttackCooldown(100);
    const start = Date.now();
    const tick = setInterval(() => {
      const elapsed = Date.now() - start;
      const pct = Math.max(0, 100 - (elapsed / ATTACK_COOLDOWN_MS) * 100);
      setAttackCooldown(pct);
      if (pct === 0) clearInterval(tick);
    }, 50);
    return () => clearInterval(tick);
  }, [isAttacking]);

  // ── Potion cooldown countdown timers ────────────────────────────────────
  useEffect(() => {
    if (healCd <= 0) return;
    const t = setTimeout(() => setHealCd(p => Math.max(0, p - 1)), 1000);
    return () => clearTimeout(t);
  }, [healCd]);

  useEffect(() => {
    if (xpCd <= 0) return;
    const t = setTimeout(() => setXpCd(p => Math.max(0, p - 1)), 1000);
    return () => clearTimeout(t);
  }, [xpCd]);

  // ── Out-of-combat HP regeneration ──────────────────────────────────────
  // 2 % max HP per second once 6s have passed since last hit.
  // Syncs new HP to the backend every 10 s so reconnecting restores correct HP.
  useEffect(() => {
    if (step !== 'game' || !player) return;
    const regen = setInterval(() => {
      const secsSinceCombat = (Date.now() - lastCombatTime) / 1000;
      if (secsSinceCombat < 6) return;
      setPlayer((prev: any) => {
        if (!prev || prev.hp >= prev.max_hp) return prev;
        const tick = Math.max(1, Math.floor(prev.max_hp * 0.02));
        const newHp = Math.min(prev.max_hp, prev.hp + tick);
        // Persist to backend every ~10 s — fire-and-forget, regen is best-effort
        const now = Date.now();
        if (playerId && now - lastRegenSyncRef.current >= 10_000) {
          lastRegenSyncRef.current = now;
          fetch(`http://localhost:8000/action/rest/${playerId}?hp=${newHp}`, { method: 'POST' }).catch(() => {});
        }
        return { ...prev, hp: newHp };
      });
    }, 1000);
    return () => clearInterval(regen);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, lastCombatTime]);

  const renderTooltip = () => {
    if (!hoveredItem) return null;

    const x = mousePos.x + 20;
    const y = mousePos.y + 20;

    const rarityColor: Record<string, string> = {
      Common:    'text-white/70',
      Uncommon:  'text-green-400',
      Rare:      'text-blue-400',
      Epic:      'text-purple-400',
      Legendary: 'text-orange-400',
    };

    // Comparison vs currently equipped slot (only for inventory items)
    const equipped = hoveredItem._fromInventory && hoveredItem.slot
      ? player?.equipment?.[hoveredItem.slot]
      : null;
    const equippedSum: number = equipped?.stats
      ? Object.values(equipped.stats as Record<string, number>).reduce((a, b) => a + b, 0)
      : 0;
    const newSum: number = hoveredItem.stats
      ? Object.values(hoveredItem.stats as Record<string, number>).reduce((a, b) => a + b, 0)
      : 0;
    const delta = newSum - equippedSum;
    const statKey = Object.keys(hoveredItem.stats || {})[0] || 'stat';

    return (
      <div className="modern-tooltip" style={{ left: x, top: y }}>
        <div className="tooltip-header">
          <div className={`tooltip-name ${rarityColor[hoveredItem.rarity] || 'text-white'}`}>
            {hoveredItem.name}
          </div>
          <div className="tooltip-slot">{hoveredItem.slot?.replace(/_/g, ' ')}</div>
        </div>

        <div className="tooltip-body">
          {hoveredItem.stats && Object.entries(hoveredItem.stats).length > 0 ? (
            <div className="space-y-2">
              {Object.entries(hoveredItem.stats).map(([k, v]: any) => (
                <div key={k} className="tooltip-stat-row">
                  <span className="tooltip-stat-label">{k.replace('_', ' ')}</span>
                  <span className="tooltip-stat-value">+{v}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-[10px] text-white/20 italic">No primary attributes</div>
          )}

          {/* Stat comparison */}
          {equipped && equipped.name !== 'None' && (
            <div className={`mt-2 pt-2 border-t border-white/10 text-[10px] font-bold ${delta > 0 ? 'text-green-400' : delta < 0 ? 'text-red-400' : 'text-white/40'}`}>
              {delta > 0
                ? `▲ +${delta} ${statKey} upgrade over [${equipped.name}]`
                : delta < 0
                ? `▼ ${delta} ${statKey} downgrade vs [${equipped.name}]`
                : `= Equal to equipped [${equipped.name}]`}
            </div>
          )}
          {equipped && equipped.name === 'None' && hoveredItem._fromInventory && (
            <div className="mt-2 pt-2 border-t border-white/10 text-[10px] text-green-400 font-bold">
              ▲ Empty slot — instant upgrade
            </div>
          )}

          {hoveredItem._fromInventory && (
            <div className="mt-1 text-[9px] text-accent/50 uppercase tracking-widest">Click to equip</div>
          )}

          <div className="tooltip-description">
            "{hoveredItem.description || "A relic of an age long past."}"
          </div>
          <div className="tooltip-bound">[ {hoveredItem.rarity || 'Common'} · Soulbound ]</div>
        </div>
      </div>
    );
  };
  useEffect(() => {
    if (combatFlash) {
      document.body.classList.add('combat-flash');
    } else {
      document.body.classList.remove('combat-flash');
    }
  }, [combatFlash]);

  // World Ticker Polling
  useEffect(() => {
    if (step === 'game' && playerId) {
      const interval = setInterval(async () => {
        try {
          const res = await fetch(`http://localhost:8000/zone/${player?.current_zone_id}`);
          const data = await res.json();
          if (data) {
            setZone(data);
            const msgs: string[] = data.world_messages || [];
            msgs.forEach((msg: string) => {
              if (!seenWorldMessages.current.has(msg)) {
                seenWorldMessages.current.add(msg);
                addLog(`🌐 ${msg}`, 'hint');
              }
            });
          }
        } catch (e) { console.error("Ticker failed", e); }
      }, 5000);
      return () => clearInterval(interval);
    }
  }, [step, playerId, player?.current_zone_id]);

  // World Chat Auto-Scroll
  useEffect(() => {
    if (chatScrollRef.current) {
      chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
    }
  }, [globalChat]);

  // Keep idleChatRef synced so the timer interval never has stale closures
  useEffect(() => {
    idleChatRef.current = { zone, player, globalChat };
  }, [zone, player, globalChat]);

  // Keep combat ref in sync with autoAttackTarget
  useEffect(() => {
    isInCombatRef.current = autoAttackTarget !== null;
  }, [autoAttackTarget]);

  // Sim players occasionally initiate chat unprompted (~every 30-60s, 60% fire chance)
  useEffect(() => {
    if (step !== 'game') return;
    const interval = setInterval(async () => {
      if (Math.random() > 0.6) return;
      const { zone: z, player: p, globalChat: chat } = idleChatRef.current;
      const allSimNames = (z?.simulated_players || []).map((sp: any) => sp.name).filter(Boolean);
      const lastSpeaker = [...chat].reverse().find((m: any) => allSimNames.includes(m.name))?.name;
      const eligibleSims = lastSpeaker ? allSimNames.filter((n: string) => n !== lastSpeaker) : allSimNames;
      const simNames = eligibleSims.join(',');
      if (!simNames) return;
      const currentLoc = z?.locations?.find((l: any) => l.id === p?.current_location_id);
      const nowTs = Date.now() / 1000;
      const aliveMobNames = (currentLoc?.mobs || [])
        .filter((m: any) => !m.respawn_at || m.respawn_at <= nowTs)
        .map((m: any) => m.name).join(', ');
      const timeVal = z?.time_of_day ?? 0.5;
      const timeStr = timeVal < 0.25 ? 'midnight' : timeVal < 0.5 ? 'dawn' : timeVal < 0.75 ? 'afternoon' : 'dusk';
      const historyText = chat.slice(-5).map((m: any) => `[${m.name}]: ${m.text}`).join('\n');
      const ambientPrompts = [
        'anyone else out here?',
        'how\'s the loot today?',
        'this zone been good to anyone?',
        'heads up out there',
        'anyone farming the elites?',
      ];
      const prompt = ambientPrompts[Math.floor(Math.random() * ambientPrompts.length)];
      try {
        const params = new URLSearchParams({
          message: prompt,
          player_name: '__ambient__',
          history: historyText,
          zone_name: z?.name || '',
          location_name: currentLoc?.name || '',
          weather: z?.weather || '',
          mobs_nearby: aliveMobNames,
          time_of_day: timeStr,
          sim_player_names: simNames,
        });
        const abortCtrl = new AbortController();
        idleChatAbortRef.current = abortCtrl;
        const res = await fetch(`http://localhost:8000/narrative/world_chat?${params}`, { method: 'POST', signal: abortCtrl.signal });
        idleChatAbortRef.current = null;
        if (!res.ok) return;
        const data = await res.json();
        if (!data.name || !data.text) return;
        const addIdle = (entry: { name: string; text: string }) => {
          setGlobalChat(prev => {
            const replyText = entry.text.toLowerCase().replace(/[^a-z0-9 ]/g, '').trim();
            const isDupe = prev.slice(-8).some((m: any) => {
              if (m.name === entry.name && prev[prev.length - 1]?.name === entry.name) return true;
              const mText = m.text.toLowerCase().replace(/[^a-z0-9 ]/g, '').trim();
              if (mText === replyText) return true;
              const aWords = new Set(replyText.split(' '));
              const bWords = mText.split(' ');
              const shared = bWords.filter((w: string) => aWords.has(w)).length;
              return shared / Math.max(aWords.size, bWords.length) > 0.8;
            });
            if (isDupe) return prev;
            return [...prev.slice(-19), entry];
          });
        };
        addIdle({ name: data.name, text: data.text });
      } catch (e: any) { if (e?.name !== 'AbortError') console.warn('idle chat error', e); }
    }, 30000 + Math.random() * 30000);
    return () => clearInterval(interval);
  }, [step]);

  // Stamp logout time so rested XP accumulates while offline
  useEffect(() => {
    if (!playerId) return;
    const handleUnload = () => {
      navigator.sendBeacon(`http://localhost:8000/action/logout/${playerId}`);
    };
    window.addEventListener('beforeunload', handleUnload);
    return () => window.removeEventListener('beforeunload', handleUnload);
  }, [playerId]);

  // Action Keybinds [1-9]
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (document.activeElement?.tagName === 'INPUT' || document.activeElement?.tagName === 'TEXTAREA') return;
      if (step !== 'game') return;

      const key = /^[1-9]$/.test(e.key) ? e.key : e.key === '?' ? '?' : null;
      if (key) {
        const cmd = getToolbarActions()[key];
        if (cmd) executeCommand(cmd);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [step, zone, player]);

  const addLog = (text: string, type: 'system' | 'player' | 'hint' | 'combat' | 'error') => {
    // Auto-detect hint patterns in strings
    const finalType = (text.includes('HINT:') || text.includes('TIP:')) ? 'hint' : type;
    setLogs(prev => [...prev.slice(-99), { text, type: finalType }]);
  };

  // Inline markdown: **bold**, *italic*, `code`
  const parseMarkdown = (text: string): React.ReactNode => {
    const regex = /\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`/g;
    const parts: React.ReactNode[] = [];
    let lastIdx = 0;
    let match;
    let key = 0;
    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIdx) parts.push(text.slice(lastIdx, match.index));
      if (match[1] !== undefined)
        parts.push(<strong key={key++} className="text-accent font-bold">{match[1]}</strong>);
      else if (match[2] !== undefined)
        parts.push(<em key={key++} className="italic opacity-80">{match[2]}</em>);
      else if (match[3] !== undefined)
        parts.push(<code key={key++} className="font-mono text-accent/80 text-[0.9em]">{match[3]}</code>);
      lastIdx = match.index + match[0].length;
    }
    if (lastIdx < text.length) parts.push(text.slice(lastIdx));
    if (parts.length === 0) return <>{text}</>;
    return <>{parts.map((p, i) => <span key={i}>{p}</span>)}</>;
  };

  const renderLogText = (text: string) => {
    const bracketRegex = /\[([^\]]+)\]/g;
    
    // 1. Detect bracketed options like [Human] for selection
    if (text.includes('[')) {
      const parts: (string | React.ReactNode)[] = [];
      const split = text.split(bracketRegex);
      let hasMatches = false;
      split.forEach((s, idx) => {
        if (idx % 2 === 1) { // This is the content inside brackets
          hasMatches = true;
          parts.push(
            <span
              key={`${s}-${idx}-${Math.random()}`}
              className="clickable-entity !text-accent hover:!text-white border-b border-accent/40 hover:border-white transition-all cursor-pointer font-bold px-1 rounded bg-accent/10"
              onClick={(e) => {
                e.stopPropagation();
                executeCommand(s);
              }}
              style={{ pointerEvents: 'auto' }}
              title={`Click to select ${s}`}
            >
              {s}
            </span>
          );
        } else if (s) {
          parts.push(parseMarkdown(s));
        }
      });
      if (hasMatches) return <>{parts.map((p, i) => <span key={i}>{p}</span>)}</>;
    }

    // 2. Detect entities (NPCs/Mobs)
    const currentLocation = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
    const entities = [
      ...(currentLocation?.npcs || []),
      ...(currentLocation?.mobs || []),
      ...(zone?.simulated_players?.filter((sp: any) => sp.current_location_id === player?.current_location_id) || [])
    ];

    if (entities.length === 0 || text.startsWith('>')) return <span>{parseMarkdown(text)}</span>;

    let parts: (string | React.ReactNode)[] = [text];
    let newParts: (string | React.ReactNode)[] = [];
    parts.forEach(part => {
      if (typeof part !== 'string') {
        newParts.push(part);
        return;
      }
      
      let subParts: (string | React.ReactNode)[] = [part];
      entities.forEach(entity => {
        const name = entity.name;
        let nextSubParts: (string | React.ReactNode)[] = [];
        subParts.forEach(sp => {
          if (typeof sp !== 'string') {
            nextSubParts.push(sp);
            return;
          }
          const split = sp.split(new RegExp(`(${name})`, 'gi'));
          split.forEach(s => {
            if (s.toLowerCase() === name.toLowerCase()) {
              const cmd = entity.role === 'vendor' ? 'shop' : entity.role === 'quest_giver' ? `talk to ${name}` : `look ${name}`;
              nextSubParts.push(
                <span
                  key={`${name}-${Math.random()}`}
                  className="clickable-entity"
                  onClick={(e) => {
                    e.stopPropagation();
                    executeCommand(cmd);
                  }}
                  title={`Click to ${cmd}`}
                >
                  {s}
                </span>
              );
            } else if (s) {
              nextSubParts.push(parseMarkdown(s));
            }
          });
        });
        subParts = nextSubParts;
      });
      newParts.push(...subParts);
    });

    return <>{newParts.map((p, i) => <span key={i}>{p}</span>)}</>;
  };

  const renderTargetFrame = () => {
    if (isGathering) {
      const secsRemaining = Math.max(0, ((100 - gatherCooldown) / 100) * 8).toFixed(1);
      return (
        <div className="target-frame">
          <div className="gather-panel">
            <div className="gather-label">
              <span>Gathering Resources</span>
              <span>{secsRemaining}s</span>
            </div>
            <div style={{ height: '10px', background: '#000', border: '1px solid #7a5c00', borderRadius: '2px', overflow: 'hidden' }}>
              <div ref={gatherBarRef} style={{
                width: '0%',
                height: '100%',
                background: 'linear-gradient(to right, #a07800, #ffe033)',
                boxShadow: '0 0 12px rgba(255,200,0,0.5)',
              }} />
            </div>
          </div>
        </div>
      );
    }
    if (!target) return null;
    return (
      <div className="target-frame">
        <div className="glass-panel target-panel">
          <div className="target-name">
            <span>{target.name}</span>
            <span className="text-[10px] opacity-60">LV {target.level}</span>
          </div>
          <div className="progress-container h-2 mt-1 border-[#600000]">
            <div
              className="progress-fill target-hp-fill"
              style={{ width: `${(target.hp / (target.max_hp || 100)) * 100}%` }}
            />
          </div>
          {targetDescription && (
            <p style={{ margin: '6px 0 0', fontSize: '11px', lineHeight: '1.4', color: '#a07850', fontStyle: 'italic', opacity: 0.85 }}>
              {targetDescription}
            </p>
          )}
        </div>
      </div>
    );
  };

  const renderMap = () => {
    const currentLoc = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
    if (!currentLoc) return null;

    const nowSec = Date.now() / 1000;
    const npcs = currentLoc.npcs || [];
    // Only show alive mobs
    const aliveMobs = (currentLoc.mobs || []).filter((m: any) => !m.respawn_at || m.respawn_at <= nowSec);
    const deadMobs  = (currentLoc.mobs || []).filter((m: any) => m.respawn_at && m.respawn_at > nowSec);
    // Sim players at this location
    const simHere = (zone?.simulated_players || []).filter((sp: any) => sp.current_location_id === player?.current_location_id);

    // Day/Night Icon
    const time = zone?.time_of_day || 0.5;
    const isDay = time > 0.25 && time < 0.75;
    const timeIcon = isDay ? "🔆" : "🌙";

    // Deterministic blip positions spread around a circle
    const ringPos = (i: number, total: number, radiusPct: number, offsetAngle = 0) => {
      const angle = (2 * Math.PI * i / Math.max(total, 1)) + offsetAngle;
      return {
        top: `${50 + radiusPct * Math.sin(angle)}%`,
        left: `${50 + radiusPct * Math.cos(angle)}%`,
      };
    };

    return (
      <div className="minimap-container mt-4">
        <div className="minimap-circle">
          <div className="minimap-overlay" />

          <div className="minimap-label label-n">N</div>
          <div className="minimap-label label-s">S</div>
          <div className="minimap-label label-e">E</div>
          <div className="minimap-label label-w">W</div>

          {/* Player (center) */}
          <div className="blip blip-player" style={{ top: '50%', left: '50%' }} title="You" />

          {/* NPCs — inner ring */}
          {npcs.map((n: any, i: number) => (
            <div key={n.id} className="blip blip-npc"
              style={ringPos(i, npcs.length, 18, Math.PI / 4)}
              title={`NPC: ${n.name}`} />
          ))}

          {/* Alive mobs — mid ring */}
          {aliveMobs.map((m: any, i: number) => (
            <div key={m.id} className="blip blip-mob"
              style={ringPos(i, aliveMobs.length, 30)}
              title={`${m.name} (Lv ${m.level})`} />
          ))}

          {/* Dead mobs — same positions but dimmed */}
          {deadMobs.map((m: any, i: number) => (
            <div key={m.id} className="blip blip-mob"
              style={{ ...ringPos(i + aliveMobs.length, aliveMobs.length + deadMobs.length, 30), opacity: 0.2 }}
              title={`${m.name} — dead (respawning)`} />
          ))}

          {/* Sim players at this location — outer ring */}
          {simHere.map((sp: any, i: number) => (
            <div key={sp.id} className="blip blip-npc"
              style={{ ...ringPos(i, simHere.length, 38, Math.PI), filter: 'hue-rotate(90deg)', opacity: 0.85 }}
              title={`${sp.name} (player)`} />
          ))}
        </div>

        <div className="time-indicator" title={`Time: ${Math.floor(time * 24)}:00`}>
          {timeIcon}
        </div>
      </div>
    );
  };

  const renderPaperdoll = () => {
    if (!player?.equipment) return null;
    return (
      <div className="paperdoll-container mt-4">
        {Object.entries(player.equipment).map(([slot, item]: [string, any]) => {
          // item is now always an object from the backend
          const hasItem = item && item.name && item.name !== "None";

          return (
            <div
              key={slot}
              className={`equipment-slot ${hasItem ? 'has-item border-l-2 border-accent/20 hover:border-l-accent cursor-pointer group' : 'opacity-20'}`}
              onMouseEnter={() => hasItem && setHoveredItem({ ...item, slot })}
              onMouseLeave={() => setHoveredItem(null)}
            >
              <div className="slot-label">{slot.replace('_', ' ')}</div>
              <div className="item-name">
                {hasItem ? item.name : 'None'}
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  const renderInventory = () => {
    const inventory = player?.inventory || [];
    const paddedInv = [...inventory];
    while (paddedInv.length < 16) paddedInv.push({ name: null });

    const rarityRing: Record<string, string> = {
      Uncommon: 'ring-1 ring-green-600/50',
      Rare:     'ring-1 ring-blue-500/60',
      Epic:     'ring-1 ring-purple-500/70',
      Legendary:'ring-2 ring-orange-400/90',
    };

    return (
      <div className="inventory-grid mt-4">
        {paddedInv.map((item: any, i: number) => {
          const hasItem = item && item.name;
          const ringClass = hasItem ? (rarityRing[item.rarity] || '') : '';
          return (
            <div
              key={i}
              className={`inventory-slot ${hasItem ? `has-item group ${ringClass}` : 'empty'} ${hasItem ? 'cursor-pointer hover:ring-1 hover:ring-accent/60' : ''}`}
              onMouseEnter={() => hasItem && setHoveredItem({ ...item, _fromInventory: true })}
              onMouseLeave={() => setHoveredItem(null)}
              onClick={() => hasItem && executeCommand(`equip ${item.name}`)}
              title={hasItem ? `${item.name} — click to equip` : ''}
            >
              {hasItem && (
                <div className="inventory-item-icon">
                  {item.name[0]}
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  };


  const renderPotions = () => {
    const consumables = (player?.inventory || []).filter((i: any) => i.slot === 'consumable');
    if (consumables.length === 0) return (
      <div className="text-xs text-gray-600 italic">No potions — buy from vendor.</div>
    );

    // Deduplicate by name so stacked potions show as "Healing Potion ×3"
    const counts: Record<string, { item: any; count: number }> = {};
    consumables.forEach((i: any) => {
      if (counts[i.name]) counts[i.name].count++;
      else counts[i.name] = { item: i, count: 1 };
    });

    return (
      <div className="space-y-1">
        {Object.values(counts).map(({ item, count }) => {
          const isHeal = !!item.stats?.heal_pct;
          const isXp   = !!item.stats?.xp_bonus_pct;
          const cd     = isHeal ? healCd : isXp ? xpCd : 0;
          const onCd   = cd > 0;

          return (
            <div key={item.name} className="flex items-center gap-2">
              <span className="text-base">{isHeal ? '🧪' : '✨'}</span>
              <div className="flex-1 min-w-0">
                <div className="text-xs text-gray-200 truncate">
                  {item.name}{count > 1 ? ` ×${count}` : ''}
                </div>
                {isXp && activeXpBuff && (
                  <div className="text-xs text-yellow-400">+{activeXpBuff.bonus_pct}% XP · {activeXpBuff.charges} kills left</div>
                )}
                {onCd && (
                  <div className="text-xs text-gray-500">{cd}s cooldown</div>
                )}
              </div>
              <button
                className={`px-2 py-0.5 text-xs border transition-colors ${
                  onCd
                    ? 'text-gray-600 border-gray-800 cursor-not-allowed'
                    : 'text-green-400 border-green-800 hover:text-green-300 hover:border-green-500'
                }`}
                disabled={onCd}
                onClick={() => usePotion(item.id)}
              >
                {onCd ? `${cd}s` : 'USE'}
              </button>
            </div>
          );
        })}
      </div>
    );
  };

  // ── Dungeon combat theater ────────────────────────────────────────────────
  const renderDungeonTheater = () => {
    if (!dungeonRun) return null;
    const run     = dungeonRun;
    const room    = run.rooms?.[run.room_index];
    const aliveMobs   = (room?.mobs || []).filter((m: any) => m.hp > 0);
    const boss    = room?.mobs?.find((m: any) => m.is_named || m.is_elite) || room?.mobs?.[0];
    const primaryMob  = aliveMobs[0] || boss;
    const roomCleared = room?.cleared || aliveMobs.length === 0;
    const isLastRoom  = run.room_index >= (run.rooms?.length ?? 1) - 1;
    const hpPct = (hp: number, max: number) => Math.max(0, Math.min(100, (hp / (max || 1)) * 100));

    const hpColor = (pct: number) =>
      pct > 60 ? 'bg-green-600' : pct > 30 ? 'bg-yellow-500' : 'bg-red-600';

    return (
      <div className="glass-panel flex-1 flex flex-col p-3 gap-2 font-mono text-xs">
        {/* Header */}
        <div className="flex justify-between items-center border-b border-white/10 pb-2">
          <span className="text-purple-300 font-bold tracking-wider">
            ⚔ {run.dungeon_name?.toUpperCase()}
          </span>
          <span className="text-gray-500">
            Room {run.room_index + 1} / {run.rooms?.length ?? 3}
          </span>
        </div>

        {/* Boss / primary mob HP */}
        {primaryMob && (
          <div className="bg-black/30 rounded p-2">
            <div className="flex justify-between mb-1">
              <span className={`font-bold ${primaryMob.is_named ? 'text-purple-300' : primaryMob.is_elite ? 'text-orange-400' : 'text-red-400'}`}>
                {primaryMob.is_named ? '⚑ ' : primaryMob.is_elite ? '★ ' : ''}{primaryMob.name}
                {aliveMobs.length > 1 && <span className="text-gray-500 ml-1">+{aliveMobs.length - 1} more</span>}
              </span>
              <span className="text-gray-400">{primaryMob.hp} / {primaryMob.max_hp} HP</span>
            </div>
            <div className="progress-container" style={{ height: '8px' }}>
              <div className="target-hp-fill transition-all duration-300"
                style={{ width: `${hpPct(primaryMob.hp, primaryMob.max_hp)}%`, height: '100%', borderRadius: '1px' }} />
            </div>
          </div>
        )}

        {run.boss_enraged && !roomCleared && (
          <div className="text-center text-red-400 font-bold py-1 border border-red-800/50 bg-red-900/20 rounded animate-pulse">
            ⚡ ENRAGED — BOSS DAMAGE +40%
          </div>
        )}
        {roomCleared && (
          <div className={`text-center font-bold py-1 border rounded ${
            run.status === 'cleared' && run.is_raid
              ? 'text-purple-300 border-purple-700/50 bg-purple-900/20'
              : 'text-yellow-400 border-yellow-800/50 bg-yellow-900/20'
          }`}>
            {run.status === 'cleared' && run.is_raid
              ? '★ RAID CLEARED — NEW TIER UNLOCKED'
              : run.status === 'cleared'
              ? '★ DUNGEON CLEARED!'
              : '✓ ROOM CLEARED — ADVANCE WHEN READY'}
          </div>
        )}

        {/* Party rows */}
        <div className="flex flex-col gap-1 flex-1">
          <div className="text-gray-600 text-[10px] tracking-widest mb-1">── PARTY ──</div>

          {/* Player row */}
          <div className="flex items-center gap-2 bg-black/20 rounded px-2 py-1">
            <span className="w-14 text-accent font-bold truncate">{player?.name || 'YOU'}</span>
            <span className="w-14 text-gray-500 truncate">{player?.char_class}</span>
            <div className="flex-1 progress-container" style={{ height: '6px' }}>
              <div className={`${hpColor(hpPct(player?.hp ?? 1, player?.max_hp ?? 1))} h-full transition-all duration-300`}
                style={{ width: `${hpPct(player?.hp ?? 1, player?.max_hp ?? 1)}%`, borderRadius: '1px' }} />
            </div>
            <span className="w-16 text-right text-gray-400 text-[10px]">{player?.hp}/{player?.max_hp}</span>
          </div>

          {/* AI party member rows */}
          {(run.party || []).map((m: any) => {
            const pct = hpPct(m.hp, m.max_hp);
            const roleColor = m.role === 'healer' ? 'text-green-400' : m.role === 'tank' ? 'text-blue-400' : 'text-red-400';
            return (
              <div key={m.id} className={`flex items-center gap-2 bg-black/20 rounded px-2 py-1 ${!m.is_alive ? 'opacity-30' : ''}`}>
                <span className="w-14 text-gray-200 font-bold truncate">{m.name}</span>
                <span className={`w-14 truncate text-[10px] ${roleColor}`}>{m.char_class}</span>
                <div className="flex-1 progress-container" style={{ height: '6px' }}>
                  {m.is_alive
                    ? <div className={`${hpColor(pct)} h-full transition-all duration-300`}
                        style={{ width: `${pct}%`, borderRadius: '1px' }} />
                    : <div className="bg-gray-800 h-full w-full" style={{ borderRadius: '1px' }} />
                  }
                </div>
                <span className="w-28 text-right text-gray-500 text-[10px] truncate">{m.is_alive ? m.last_action : '💀 DEAD'}</span>
              </div>
            );
          })}
        </div>

        {/* Rolling combat log */}
        <div className="border-t border-white/10 pt-2">
          <div className="text-gray-600 text-[10px] tracking-widest mb-1">── LOG ──</div>
          {(run.combat_log || []).slice(-3).map((line: string, i: number) => (
            <div key={i} className="text-gray-400 text-[10px] leading-5">▶ {line}</div>
          ))}
          {(run.combat_log || []).length === 0 && (
            <div className="text-gray-600 text-[10px]">Entering {room?.name}...</div>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex gap-2 pt-1 border-t border-white/10">
          {run.status === 'active' && !roomCleared && (
            <button
              className={`tool-button flex-1 !text-red-400 !border-red-900/50 relative overflow-hidden ${dungeonAttacking ? 'opacity-60' : ''}`}
              disabled={dungeonAttacking}
              onClick={async () => {
                if (!playerId || dungeonAttacking) return;
                setDungeonAttacking(true);
                try {
                  const res = await fetch(`http://localhost:8000/dungeon/attack/${run.id}?player_id=${playerId}`, { method: 'POST' });
                  if (!res.ok) { const e = await res.json(); addLog(e.detail || 'Dungeon error', 'error'); return; }
                  const data = await res.json();
                  setDungeonRun(data.run);
                  setPlayer((prev: any) => prev ? {
                    ...prev,
                    hp:            data.player_hp,
                    max_hp:        data.player_max_hp,
                    xp:            data.player_xp,
                    gold:          data.player_gold,
                    level:         data.player_level,
                    damage:        data.player_damage        ?? prev.damage,
                    next_level_xp: data.player_next_level_xp ?? prev.next_level_xp,
                    raids_cleared:    data.player_raids_cleared    ?? prev.raids_cleared,
                    dungeons_cleared: data.player_dungeons_cleared ?? prev.dungeons_cleared,
                    inventory:     data.player_inventory ?? prev.inventory,
                  } : prev);
                  if (data.loot?.length) {
                    data.loot.forEach((item: any) => {
                      if (item._dropped) addLog(`⚠ Bags full — [${item.name}] left on the ground!`, 'error');
                      else addLog(`🎒 ${item.name} (${item.rarity}) dropped!`, 'system');
                    });
                  }
                  if (data.leveled_up) addLog(`⬆ LEVEL UP! Now level ${data.player_level}!`, 'system');
                  if (data.wiped) {
                    addLog('☠ Your party was wiped. Retreating...', 'error');
                    await fetch(`http://localhost:8000/dungeon/flee/${dungeonRun.id}?player_id=${playerId}`, { method: 'POST' }).catch(() => {});
                    setDungeonRun(null);
                  }
                } catch (e: any) { addLog(`Dungeon Error: ${e.message}`, 'error'); }
                finally { setDungeonAttacking(false); }
              }}
            >
              {dungeonAttacking ? '...' : '⚔ ATTACK'}
            </button>
          )}

          {run.status === 'active' && roomCleared && !isLastRoom && (
            <button
              className="tool-button flex-1 !text-yellow-400 !border-yellow-800/50"
              onClick={async () => {
                const res = await fetch(`http://localhost:8000/dungeon/advance/${run.id}?player_id=${playerId}`, { method: 'POST' });
                if (res.ok) { const d = await res.json(); setDungeonRun(d); addLog(`→ Entering ${d.rooms?.[d.room_index]?.name}...`, 'system'); }
              }}
            >
              ADVANCE →
            </button>
          )}

          {(run.status === 'cleared' || (run.status === 'active' && roomCleared && isLastRoom)) && (
            <button
              className="tool-button flex-1 !text-yellow-400 !border-yellow-700/60"
              onClick={async () => {
                await fetch(`http://localhost:8000/dungeon/flee/${run.id}?player_id=${playerId}`, { method: 'POST' });
                setDungeonRun(null);
                addLog('You leave the dungeon, victorious.', 'system');
              }}
            >
              ★ RETURN TO WORLD
            </button>
          )}

          {run.status === 'active' && (
            <button
              className="tool-button !text-gray-500 !border-gray-800"
              onClick={async () => {
                await fetch(`http://localhost:8000/dungeon/flee/${run.id}?player_id=${playerId}`, { method: 'POST' });
                setDungeonRun(null);
                addLog('You flee the dungeon.', 'system');
              }}
            >
              FLEE
            </button>
          )}
        </div>
      </div>
    );
  };

  const renderWeather = () => {
    const weather = zone?.weather || "sunny";
    const weatherIcons: any = {
      sunny: "☀️",
      rainy: "🌧️",
      foggy: "🌫️",
      stormy: "⛈️",
      snowy: "❄️"
    };

    const timeVal = zone?.time_of_day ?? 0.5;
    const timeStr = timeVal < 0.25 ? 'Midnight' : timeVal < 0.5 ? 'Dawn' : timeVal < 0.75 ? 'Afternoon' : 'Dusk';
    const currentLoc2 = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
    const nowTs3 = Date.now() / 1000;
    const nearbyMobCount = (currentLoc2?.mobs || []).filter((m: any) => !m.respawn_at || m.respawn_at <= nowTs3).length;
    const activeQuest = player?.active_quests?.[0];
    const completedCount = (player?.active_quests || []).filter((q: any) => q.is_completed).length;
    const vendorHere = currentLoc2?.npcs?.some((n: any) => n.role === 'vendor');
    const questGiverHere = currentLoc2?.npcs?.some((n: any) => n.role === 'quest_giver');

    // Derive next-step guidance based on exact loop stage
    const lvl = player?.level || 1;
    const gs = gearScore ?? 0;
    const zoneMaxLvl = Math.max(...(zone?.level_range || [1, 5]));
    const requiredGs = zoneMaxLvl * 25;
    let progressSlot: string;
    let nextStepSlot: string;

    if (lvl < 10) {
      progressSlot = `GS: ${gs} — LEVEL ${lvl} / 10 NEEDED FOR DUNGEONS`;
      nextStepSlot = `LOOP: GRIND QUESTS → REACH LEVEL 10 → ENTER DUNGEONS`;
    } else if (lvl < 20) {
      progressSlot = `GS: ${gs} / ${requiredGs} REQUIRED — LEVEL ${lvl} / 20 NEEDED FOR RAIDS`;
      nextStepSlot = gs >= requiredGs
        ? `✓ GS MET — REACH LEVEL 20 TO UNLOCK RAIDS THEN TYPE 'TRAVEL'`
        : `LOOP: RUN DUNGEONS → BUILD GEAR SCORE → UNLOCK RAIDS AT LEVEL 20`;
    } else if (gs < requiredGs) {
      progressSlot = `GS: ${gs} / ${requiredGs} REQUIRED TO ADVANCE`;
      nextStepSlot = `LOOP: FARM RAIDS FOR EPIC GEAR → HIT ${requiredGs} GS → TYPE 'TRAVEL' TO ADVANCE`;
    } else {
      progressSlot = `✓ GS: ${gs} / ${requiredGs} — ZONE COMPLETE`;
      nextStepSlot = `ZONE CLEARED — TYPE 'TRAVEL' TO ADVANCE TO THE NEXT CHALLENGE`;
    }

    const tickerMessages = [
      `ATMOSPHERE: ${weather.toUpperCase()} — ${timeStr.toUpperCase()} ${weatherIcons[weather] || "☀️"}`,
      zone?.name ? `ZONE: ${zone.name.toUpperCase()} — ${currentLoc2?.name?.toUpperCase() || ''}` : "EXPLORING THE REALM",
      nearbyMobCount > 0
        ? `⚔ DANGER NEARBY: ${nearbyMobCount} CREATURE${nearbyMobCount > 1 ? 'S' : ''} IN THIS AREA — STAY ALERT`
        : "✓ THIS AREA IS CLEAR — SAFE TO REST",
      completedCount > 0
        ? `★ ${completedCount} QUEST${completedCount > 1 ? 'S' : ''} READY TO TURN IN — RETURN TO THE HUB`
        : activeQuest
          ? `📜 ACTIVE: ${activeQuest.title.toUpperCase()} — ${activeQuest.current_progress}/${activeQuest.target_count} ${(activeQuest.collect_name || activeQuest.target_id).toUpperCase()}S`
          : questGiverHere ? `! QUEST GIVER HERE — TYPE 'TALK TO [NAME]'` : vendorHere ? `🛒 MERCHANT NEARBY — TYPE 'SHOP'` : "TIP: TYPE 'LOOK' TO SURVEY YOUR SURROUNDINGS",
      progressSlot,
      nextStepSlot,
    ];

    const tickerLabels = ["Weather", "Location", "Status", "Quest", "Progress", "Next Step"];

    return (
      <div className="weather-overlay">
        <div className="ticker-wrapper">
          {tickerMessages.map((msg, idx) => (
            <div key={idx} className="ticker-item">
              <span className="text-[9px] uppercase tracking-[0.2em] text-accent font-bold opacity-60">{tickerLabels[idx % tickerLabels.length]}</span>
              <span className="text-xs uppercase font-mono text-white font-bold">{msg}</span>
              <span className="mx-4 text-accent/20">•</span>
            </div>
          ))}
          {/* Duplicate for seamless loop */}
          {tickerMessages.map((msg, idx) => (
            <div key={`dup-${idx}`} className="ticker-item">
              <span className="text-[9px] uppercase tracking-[0.2em] text-accent font-bold opacity-60">{tickerLabels[idx % tickerLabels.length]}</span>
              <span className="text-xs uppercase font-mono text-white font-bold">{msg}</span>
              <span className="mx-4 text-accent/20">•</span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const describeLocation = (name: string, locDescription: string, zoneName: string) => {
    const params = new URLSearchParams({ name, loc_description: locDescription, zone: zoneName });
    fetch(`http://localhost:8000/describe/location?${params}`)
      .then(r => r.json())
      .then(d => { if (d.description) addLog(d.description, "hint"); })
      .catch(() => {});
  };

  const describeEntity = (name: string, opts: { isElite?: boolean; isNamed?: boolean; isNpc?: boolean; isDeath?: boolean } = {}) => {
    const key = opts.isDeath ? `death:${name.toLowerCase()}` : name.toLowerCase();
    if (!opts.isDeath && seenEntities.current.has(key)) return;
    if (!opts.isDeath) seenEntities.current.add(key);

    // Reserve a slot in the log NOW so the description appears adjacent to the
    // trigger message even if other combat ticks fire while the AI is responding.
    const slotId = `desc_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    setLogs(prev => [...prev,
      { text: "─────────────────────────────────────", type: "system" as const },
      { text: "...", type: "hint" as const, id: slotId },
      { text: "─────────────────────────────────────", type: "system" as const },
    ]);

    const params = new URLSearchParams({
      name,
      entity_type: opts.isDeath ? 'death' : opts.isNpc ? 'npc' : 'creature',
      is_elite: String(!!opts.isElite),
      is_named: String(!!opts.isNamed),
      zone: zone?.name || '',
    });
    fetch(`http://localhost:8000/describe/entity?${params}`)
      .then(r => r.json())
      .then(d => {
        if (d.description) {
          // Fill the reserved slot in-place — stays where it was inserted
          setLogs(prev => prev.map(e => e.id === slotId ? { ...e, text: d.description } : e));
          // Pin to target frame for creatures (not NPCs or death scenes)
          if (!opts.isNpc && !opts.isDeath) {
            entityDescCache.current.set(name, d.description);
            setTargetDescription(d.description);
          }
        } else {
          // No content — remove the whole placeholder block
          setLogs(prev => {
            const idx = prev.findIndex(e => e.id === slotId);
            if (idx < 0) return prev;
            return prev.filter((_, i) => i < idx - 1 || i > idx + 1);
          });
        }
      })
      .catch(() => {
        setLogs(prev => {
          const idx = prev.findIndex(e => e.id === slotId);
          if (idx < 0) return prev;
          return prev.filter((_, i) => i < idx - 1 || i > idx + 1);
        });
      });
  };

  const streamNarrative = async (action: string) => {
    if (!playerId) return;
    setIsTalking(true);
    try {
      const response = await fetch(`http://localhost:8000/narrative/stream/${playerId}?action=${encodeURIComponent(action)}`);
      if (!response.body) return;

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let fullText = "";

      // Add initial empty log to update
      setLogs(prev => [...prev, { text: "", type: "system" }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value);
        fullText += chunk;

        // Update the last log entry with accumulated text
        setLogs(prev => {
          const newLogs = [...prev];
          newLogs[newLogs.length - 1] = { ...newLogs[newLogs.length - 1], text: fullText };
          return newLogs;
        });
      }
    } catch (err) {
      console.error("Streaming failed:", err);
      addLog("The narrative connection was severed.", "error");
    } finally {
      setIsTalking(false);
    }
  };

  const handleWorldChat = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!worldInput.trim()) return;
    const playerMsg = worldInput.trim();
    const playerName = player?.name || "You";
    setWorldInput(""); // clear input immediately

    // Show player's own message in chat
    setGlobalChat(prev => [...prev.slice(-19), { name: playerName, text: playerMsg }]);

    const historyText = globalChat.slice(-5).map(m => `[${m.name}]: ${m.text}`).join('\n');

    // Every 10 player messages, generate a 1-sentence summary for long-term context
    chatMsgCountRef.current += 1;
    if (chatMsgCountRef.current % 10 === 0) {
      const summaryHistory = globalChat.slice(-20).map(m => `[${m.name}]: ${m.text}`).join('\n');
      try {
        const sp = new URLSearchParams({ history: summaryHistory, player_name: playerName, zone_name: zone?.name || '' });
        const sr = await fetch(`http://localhost:8000/narrative/summarize_chat?${sp}`, { method: 'POST' });
        if (sr.ok) {
          const sd = await sr.json();
          if (sd.summary) setChatSummary(sd.summary);
        }
      } catch { /* silent */ }
    }

    // Call backend for AI friend response
    try {
      const bio = biography || `${playerName} the ${player?.race} ${player?.char_class}`;
      const currentLoc = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
      const nowTs2 = Date.now() / 1000;
      const aliveMobNames = (currentLoc?.mobs || [])
        .filter((m: any) => !m.respawn_at || m.respawn_at <= nowTs2)
        .map((m: any) => m.name)
        .join(', ');
      const timeVal = zone?.time_of_day ?? 0.5;
      const timeStr = timeVal < 0.25 ? 'midnight' : timeVal < 0.5 ? 'dawn' : timeVal < 0.75 ? 'afternoon' : 'dusk';
      const questStr = (player?.active_quests || []).map((q: any) => q.title).join(', ');
      const allSimNames = (zone?.simulated_players || []).map((sp: any) => sp.name).filter(Boolean);
      const lastSimSpeaker = [...globalChat].reverse().find(m => allSimNames.includes(m.name))?.name;
      const simNames = (lastSimSpeaker ? allSimNames.filter((n: string) => n !== lastSimSpeaker) : allSimNames).join(',');
      const params = new URLSearchParams({
        message: playerMsg,
        player_name: playerName,
        player_bio: bio,
        history: historyText,
        zone_name: zone?.name || '',
        location_name: currentLoc?.name || '',
        weather: zone?.weather || '',
        mobs_nearby: aliveMobNames,
        time_of_day: timeStr,
        active_quests: questStr,
        sim_player_names: simNames,
        ...(chatSummary ? { chat_context: chatSummary } : {}),
      });
      const res = await fetch(`http://localhost:8000/narrative/world_chat?${params}`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        const responses: { name: string; text: string }[] = data.responses || (data.name ? [{ name: data.name, text: data.text }] : []);
        const addChatMsg = (entry: { name: string; text: string }) => {
          setGlobalChat(prev => {
            const replyText = (entry.text || '').toLowerCase().replace(/[^a-z0-9 ]/g, '').trim();
            // Skip if same person just spoke, or text is too similar to recent messages
            const isDupe = prev.slice(-8).some(m => {
              if (m.name === entry.name && prev[prev.length - 1]?.name === entry.name) return true;
              const mText = m.text.toLowerCase().replace(/[^a-z0-9 ]/g, '').trim();
              if (mText === replyText) return true;
              const aWords = new Set(replyText.split(' '));
              const bWords = mText.split(' ');
              const shared = bWords.filter((w: string) => aWords.has(w)).length;
              return shared / Math.max(aWords.size, bWords.length) > 0.8;
            });
            if (isDupe) return prev;
            return [...prev.slice(-19), entry];
          });
        };
        // Stagger multiple responses so they feel like separate typing moments
        responses.forEach((entry, i) => {
          setTimeout(() => addChatMsg(entry), 800 + i * (1200 + Math.random() * 800));
        });
      }
    } catch (e) {
      console.error("World Chat AI failed", e);
    }
  };

  const handleCommand = async (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() || step === 'intro') {
      await executeCommand(input);
      setInput("");
    }
  };

  const getToolbarActions = (): Record<string, string> => {
    const actions: Record<string, string> = {};
    let idx = 1;
    actions[String(idx++)] = 'look';

    const loc = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
    const exits = loc?.exits || {};
    Object.keys(exits).forEach((dir) => { actions[String(idx++)] = `go ${dir}`; });

    const nowTs = Date.now() / 1000;
    const aliveMobNames = [...new Set(
      (loc?.mobs || []).filter((m: any) => !m.respawn_at || m.respawn_at <= nowTs).map((m: any) => m.name)
    )] as string[];
    aliveMobNames.forEach((name) => { actions[String(idx++)] = `attack ${name}`; });

    const completedQuests = (player?.active_quests || []).filter((q: any) => q.is_completed);
    const hasQuestGiver = loc?.npcs?.some((n: any) => n.role === 'quest_giver');
    if (hasQuestGiver && completedQuests.length > 0) actions[String(idx++)] = 'turn in';

    (loc?.npcs || []).filter((n: any) => n.role === 'quest_giver').forEach((n: any) => {
      actions[String(idx++)] = `talk to ${n.name}`;
    });

    (loc?.npcs || []).filter((n: any) => n.role === 'vendor').forEach(() => {
      actions[String(idx++)] = 'shop';
      if ((player?.inventory || []).length > 0) actions[String(idx++)] = 'sell';
    });

    actions[String(idx++)] = 'quests';
    actions[String(idx++)] = 'inventory';
    actions[String(idx++)] = 'who';
    actions['?'] = 'help';
    return actions;
  };

  const usePotion = async (itemId: string, silent = false) => {
    if (!playerId) return;
    try {
      const res = await fetch(
        `http://localhost:8000/action/use/${playerId}?item_id=${encodeURIComponent(itemId)}`,
        { method: 'POST' }
      );
      const data = await res.json();
      if (data.success) {
        data.messages?.forEach((msg: string) => addLog(msg, 'system'));
        setPlayer((prev: any) =>
          prev ? { ...prev, hp: data.player_hp, inventory: (prev.inventory || []).filter((i: any) => i.id !== itemId) } : prev
        );
        if (data.heal_cd !== undefined) setHealCd(data.heal_cd);
        if (data.xp_cd   !== undefined) setXpCd(data.xp_cd);
        if (data.active_xp_buff !== undefined) setActiveXpBuff(data.active_xp_buff ?? null);
      } else if (!silent) {
        addLog(data.message || 'Cannot use that right now.', 'hint');
      }
    } catch { /* fire-and-forget */ }
  };

  const executeCommand = async (cmd: string) => {
    let trimmedCmd = cmd.trim();
    if (!trimmedCmd && step !== 'intro') return;

    // Resolve toolbar number / symbol shortcuts
    if (step === 'game' && /^[1-9]$|^\?$/.test(trimmedCmd)) {
      const resolved = getToolbarActions()[trimmedCmd];
      if (resolved) trimmedCmd = resolved;
      else return;
    }

    addLog(`> ${trimmedCmd}`, "player");

    if (step === 'intro') {
      try {
        const res = await fetch('http://localhost:8000/players');
        const data = await res.json();
        if (data.players?.length > 0) {
          setSavedPlayers(data.players);
          addLog("─── SAVED CHRONICLES ───", "system");
          data.players.forEach((p: any, i: number) => {
            addLog(`── Character ${i + 1} ──────────────────────`, "system");
            addLog(`[${i + 1}] ${p.name}`, "hint");
            addLog(`    ${p.race} ${p.char_class}  ·  Level ${p.level}  ·  ${p.pronouns}`, "hint");
            addLog(`    HP ${p.hp}/${p.max_hp}  ·  Gold ${p.gold}g  ·  Kills ${p.kills}  ·  Deaths ${p.deaths}`, "hint");
            addLog(`    Quests completed: ${p.completed_quest_ids?.length ?? 0}  ·  Dungeons: ${p.dungeons_cleared ?? 0}  ·  Raids: ${p.raids_cleared ?? 0}`, "hint");
          });
          addLog("────────────────────────────────────────", "system");
          addLog("[new] — Start a new character", "hint");
          addLog("Type a number to load, or 'new' to start fresh.", "hint");
          setStep('load');
        } else {
          addLog("SELECT YOUR RACE:", "system");
          RACES.forEach(race => addLog(`[${race}]: ${RACE_FLAVOR[race]}`, "hint"));
          setStep('race');
        }
      } catch {
        addLog("SELECT YOUR RACE:", "system");
        RACES.forEach(race => addLog(`[${race}]: ${RACE_FLAVOR[race]}`, "hint"));
        setStep('race');
      }
    } else if (step === 'load') {
      if (trimmedCmd.toLowerCase() === 'new') {
        setSavedPlayers([]);
        addLog("SELECT YOUR RACE:", "system");
        RACES.forEach(race => addLog(`[${race}]: ${RACE_FLAVOR[race]}`, "hint"));
        setStep('race');
      } else {
        const num = parseInt(trimmedCmd);
        const selected = !isNaN(num) && num > 0 && num <= savedPlayers.length ? savedPlayers[num - 1] : null;
        if (selected) {
          addLog("Loading your chronicle...", "system");
          try {
            const res = await fetch(`http://localhost:8000/player/${selected.player_id}`);
            if (!res.ok) throw new Error("Character not found.");
            const data = await res.json();
            setPlayer(data.player);
            setPlayerId(data.player_id);
            setZone(data.zone);
            setGearScore(data.gear_score ?? 0);
            setBiography(`Born and raised in the echoes of the world, ${data.player.name} has chosen the path of the ${data.player.char_class}. Identified as ${data.player.pronouns}, they seek glory in the Great Chronicles.`);
            if (data.player.current_location_id) {
              setExploredLocations(new Set([data.player.current_location_id]));
            }
            // Compute rested XP accumulated since last logout
            fetch(`http://localhost:8000/action/login/${data.player_id}`, { method: 'POST' })
              .then(r => r.json()).then(rd => {
                setRestedXp(rd.rested_xp ?? 0);
                setRestedXpCap(rd.rested_xp_cap ?? 0);
                if ((rd.rested_xp ?? 0) > 0) {
                  addLog(`💤 You are Rested! Next kills grant 2× XP (${rd.rested_xp} XP pool).`, 'system');
                }
              }).catch(() => {});
            const currentLoc = data.zone.locations?.find((l: any) => l.id === data.player.current_location_id) || data.zone.locations?.[0];
            setLogs([
              { text: `━━━ CHRONICLE RESUMED ━━━`, type: "system" },
              { text: `Welcome back, ${data.player.name}.`, type: "system" },
              ...(currentLoc ? [
                { text: `--- ${currentLoc.name} ---`, type: "system" as const },
                { text: currentLoc.description, type: "system" as const },
              ] : []),
            ]);
            setStep('game');
          } catch (err: any) {
            addLog(`Failed to load character: ${err.message}`, "error");
          }
        } else {
          addLog("Invalid selection. Type a number from the list, or 'new' to start fresh.", "error");
        }
      }
    } else if (step === 'race') {
      const selectedRace = RACES.find(r => r.toLowerCase() === trimmedCmd.toLowerCase());
      if (selectedRace) {
        setCreationData(prev => ({ ...prev, race: selectedRace }));
        addLog(`YOU HAVE SELECTED: ${selectedRace}`, "system");
        addLog("SELECT YOUR CLASS:", "system");
        CLASSES.forEach(c => addLog(`[${c}]: ${CLASS_FLAVOR[c]}`, "hint"));
        setStep('class');
      } else {
        addLog("Invalid race. Choose from the list above.", "error");
      }
    } else if (step === 'class') {
      const selectedClass = CLASSES.find(c => c.toLowerCase() === trimmedCmd.toLowerCase());
      if (selectedClass) {
        setCreationData(prev => ({ ...prev, charClass: selectedClass }));
        addLog(`YOU HAVE BECOME: ${selectedClass}`, "system");
        addLog("SELECT YOUR PRONOUNS:", "system");
        ["He/Him", "She/Her", "They/Them"].forEach(p => addLog(`[${p}]`, "hint"));
        setStep('gender');
      } else {
        addLog("Invalid class. Choose from the list above.", "error");
      }
    } else if (step === 'gender') {
      const pronouns = ["He/Him", "She/Her", "They/Them"];
      const selected = pronouns.find(p => p.toLowerCase().includes(trimmedCmd.toLowerCase()));
      if (selected) {
        setCreationData(prev => ({ ...prev, pronouns: selected }));
        addLog(`PRONOUNS SET TO: ${selected}`, "system");
        addLog("ENTER YOUR CHARACTER NAME:", "system");
        setStep('name');
      } else {
        addLog("Invalid selection. Choose 'He/Him', 'She/Her', or 'They/Them'.", "error");
      }
    } else if (step === 'name') {
      const name = trimmedCmd;
      addLog("Connecting to the world engine...", "system");
      try {
        const res = await fetch(`http://localhost:8000/player/create?name=${encodeURIComponent(name)}&race=${creationData.race}&char_class=${creationData.charClass}&pronouns=${encodeURIComponent(creationData.pronouns)}`, { method: 'POST' });
        if (!res.ok) throw new Error("Failed to connect to backend");
        const data = await res.json();

        setPlayer(data.player);
        setPlayerId(data.player_id);
        setZone(data.zone);
        setRestedXp(0);
        setRestedXpCap(Math.floor((data.player.next_level_xp ?? 100) * 1.5));
        addLog(`The world begins to take shape...`, "system");
        addLog(`Welcome, ${name} the ${creationData.race} ${creationData.charClass}.`, "system");

        // Clear creation logs for a fresh game start
        setLogs([
          { text: `--- ${data.zone.locations?.[0]?.name || data.zone.name} ---`, type: "system" },
          { text: data.zone.locations?.[0]?.description || data.zone.description, type: "system" }
        ]);

        setStep('game');

        // Simple bio generation (client-side for now to avoid multiple waits)
        setBiography(`Born and raised in the echoes of the world, ${name} has chosen the path of the ${creationData.charClass}. Identified as ${creationData.pronouns}, they seek glory in the Great Chronicles.`);

        if (data.player.current_location_id) {
          setExploredLocations(new Set([data.player.current_location_id]));
        }

        // Show NPC/mob list for starting location (location header already in setLogs)
        const hubLoc = data.zone.locations?.[0];
        if (hubLoc?.npcs?.length > 0) {
          addLog("PEOPLE HERE:", "hint");
          hubLoc.npcs.forEach((n: any) => {
            if (n.role === 'vendor') addLog(`- ${n.name} (Merchant) — [shop]`, "hint");
            else if (n.role === 'quest_giver') addLog(`- ${n.name} (Quest Giver) — [talk to ${n.name}]`, "hint");
            else addLog(`- ${n.name}`, "hint");
          });
        }
      } catch (err: any) {
        addLog(`Error: ${err.message}. Is the backend running?`, "error");
      }
    } else if (step === 'game') {
      const lowerCmd = trimmedCmd.toLowerCase();
      if (lowerCmd === 'help' || lowerCmd === '?') {
        addLog("══════════ COMMANDS ══════════", "system");
        addLog("MOVEMENT  go [north/south/east/west]", "hint");
        addLog("COMBAT    attack [mob] · flee (escape mid-fight)", "hint");
        addLog("QUESTS    quests · accept [1/all] · turn in · gather", "hint");
        addLog("SOCIAL    talk to [npc] · who", "hint");
        addLog("ITEMS     inventory · look · look [item/mob/npc] · equip [item] · unequip [slot]", "hint");
        addLog("POTIONS   use healing · use elixir  (or click USE in side panel)", "hint");
        addLog("ECONOMY   shop · buy [item] · sell [item] · sell junk", "hint");
        addLog("TRAVEL    travel · travel dungeon (lv10+) · travel raid (lv20+)", "hint");
        addLog("DUNGEON   attack · flee · advance  (use buttons or type commands in dungeon)", "hint");
        addLog("Any other input → AI narrative engine", "hint");
        addLog("══════════════════════════════", "system");
      } else if (lowerCmd.startsWith('look ') || lowerCmd === 'look') {
        const targetStr = lowerCmd.startsWith('look ') ? lowerCmd.substring(5).trim() : null;
        const loc = zone?.locations?.find((l: any) => l.id === player?.current_location_id);

        if (targetStr && loc) {
          const npc = loc.npcs?.find((n: any) => n.name.toLowerCase().includes(targetStr));
          const mob = loc.mobs?.find((m: any) => m.name.toLowerCase().includes(targetStr));
          const playerEntity = zone?.simulated_players?.find((sp: any) => sp.current_location_id === loc.id && sp.name.toLowerCase().includes(targetStr));
          const targetEntity = npc || mob || playerEntity;

          if (targetEntity) {
            setTarget({
              name: targetEntity.name,
              hp: targetEntity.hp !== undefined ? targetEntity.hp : 100,
              max_hp: targetEntity.max_hp || 100,
              level: targetEntity.level || 1
            });
            addLog(`You look at ${targetEntity.name}. ${targetEntity.description || (targetEntity.role === 'quest_giver' ? "They watch you expectantly." : "They seem aware of your presence.")}`, "hint");
            return;
          }

          // Check inventory for item
          const invItem = (player?.inventory || []).find((i: any) => i.name?.toLowerCase().includes(targetStr));
          if (invItem) {
            const statLines = Object.entries(invItem.stats || {}).map(([k, v]) => `${k} +${v}`).join(', ');
            addLog(`${invItem.name} [${invItem.rarity || 'Common'}] — ${invItem.slot || 'item'} · lv${invItem.level || 1}`, "hint");
            if (statLines) addLog(`  Stats: ${statLines}`, "hint");
            if (invItem.description) addLog(`  "${invItem.description}"`, "hint");
            return;
          }

          addLog(`Nothing by the name of '${targetStr}' is visible here.`, "error");
        }

        addLog(`--- ${loc?.name || zone?.name || "The Void"} ---`, "system");
        addLog(loc?.description || zone?.description || "A mysterious area.", "system");

        if (loc?.npcs?.length > 0) {
          addLog("PEOPLE HERE:", "hint");
          loc.npcs.forEach((n: any) => {
            const hasQuest = zone?.quests?.some((q: any) => !player?.active_quests?.some((aq: any) => aq.id === q.id));
            const questBadge = (hasQuest && n.role === 'quest_giver' && !revealedNpcs.has(n.id)) ? " (!)" : "";
            if (n.role === 'vendor') addLog(`- ${n.name} (Merchant) — [shop]`, "hint");
            else if (n.role === 'quest_giver') addLog(`- ${n.name}${questBadge} — [talk to ${n.name}]`, "hint");
            else addLog(`- ${n.name}`, "hint");
          });
        }

        const nowSec = Date.now() / 1000;
        const aliveMobs = (loc?.mobs || []).filter((m: any) => !m.respawn_at || m.respawn_at <= nowSec);
        const deadMobs  = (loc?.mobs || []).filter((m: any) => m.respawn_at && m.respawn_at > nowSec);
        if (aliveMobs.length > 0) {
          addLog("CREATURES HERE:", "combat");
          // Group by name for cleaner display (e.g. "3x Boar (Lv 1)")
          const grouped: Record<string, any> = {};
          aliveMobs.forEach((m: any) => {
            if (!grouped[m.name]) grouped[m.name] = { ...m, count: 0 };
            grouped[m.name].count++;
          });
          Object.values(grouped).forEach((g: any) =>
            addLog(`- ${g.count > 1 ? `${g.count}x ` : ""}${g.name} (Lv ${g.level})`, "combat")
          );
          addLog(`HINT: Type 'attack ${aliveMobs[0].name.toLowerCase()}' to begin combat!`, "hint");
        }
        if (deadMobs.length > 0) {
          const soonest = Math.ceil(Math.min(...deadMobs.map((m: any) => m.respawn_at)) - nowSec);
          addLog(`${deadMobs.length} creature(s) slain here — respawn in ~${soonest}s.`, "hint");
        }

        // Forage hint — shown when a forage quest targets this exact location
        const forageHere = (player?.active_quests || []).find((q: any) =>
          q.quest_type === 'forage' && q.target_id === player?.current_location_id && !q.is_completed
        );
        if (forageHere) {
          addLog(`✦ ${forageHere.collect_name || "Resources"} can be gathered here (${forageHere.current_progress}/${forageHere.target_count}). Click GATHER or type 'gather'.`, "hint");
        }

        if (loc?.exits && Object.keys(loc.exits).length > 0) {
          addLog("EXITS:", "hint");
          Object.entries(loc.exits).forEach(([dir, id]: [string, any]) => {
            const target = zone.locations.find((l: any) => l.id === id);
            addLog(`- ${dir.toUpperCase()}: ${target?.name || "Unknown"}`, "hint");
          });
        }

        // Only show quests if already revealed by talking
        const locQuests = zone?.quests?.filter((q: any) => !player?.active_quests?.some((aq: any) => aq.id === q.id)) || [];
        const anyGiverRevealed = (zone?.locations || []).some((l: any) =>
          (l.npcs || []).some((n: any) => n.role === 'quest_giver' && revealedNpcs.has(n.id))
        );
        const revealedQuests = anyGiverRevealed ? locQuests : [];

        if (revealedQuests.length > 0) {
          addLog("AVAILABLE QUESTS:", "hint");
          revealedQuests.forEach((q: any, idx: number) => addLog(`${idx + 1}. [ ] ${q.title}: ${q.objective}`, "hint"));
          addLog("Type 'accept [number]' or 'accept all' to begin.", "hint");
        }
      } else if (lowerCmd === 'who') {
        const players = zone?.simulated_players || [];
        const myLoc = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
        const here = players.filter((p: any) => p.current_location_id === player?.current_location_id);
        const elsewhere = players.filter((p: any) => p.current_location_id !== player?.current_location_id);
        addLog("--- CHRONICLES OF LIGHT ---", "system");
        addLog(`Total Players Online: ${players.length + 1}`, "system");
        addLog(`- ${player?.name} (Lvl ${player?.level || 1} ${player?.race} ${player?.char_class}) [${myLoc?.name ?? 'Unknown'}] - HERE`, "player");
        here.forEach((p: any) => {
          addLog(`- ${p.name} (Lvl ${p.level} ${p.race} ${p.char_class ?? p.charClass ?? '?'}) [HERE] - ${(p.status ?? 'exploring').toUpperCase()}`, "hint");
        });
        elsewhere.forEach((p: any) => {
          const pLoc = zone?.locations?.find((l: any) => l.id === p.current_location_id);
          addLog(`- ${p.name} (Lvl ${p.level} ${p.race} ${p.char_class ?? p.charClass ?? '?'}) [${pLoc?.name ?? 'elsewhere'}] - ${(p.status ?? 'exploring').toUpperCase()}`, "hint");
        });
      } else if (lowerCmd === 'quests' || lowerCmd === 'log') {
        const active = player?.active_quests || [];
        if (active.length > 0) {
          addLog("--- QUEST LOG ---", "system");
          active.forEach((q: any) => {
            addLog(`\u25cf ${q.title.toUpperCase()}`, "system");
            addLog(`   ${q.description}`, "system");
            addLog(`   Objective: ${q.objective} (${q.current_progress}/${q.target_count})`, "hint");
          });
        } else {
          addLog("Your quest log is empty. Visit a settlement to find work.", "hint");
        }
      } else if (lowerCmd.startsWith('accept ')) {
        const qFragment = cmd.substring(7).trim().toLowerCase();

        // Only revealed quests are available for acceptance
        const locQuests = zone?.quests?.filter((q: any) => !player?.active_quests?.some((aq: any) => aq.id === q.id)) || [];
        const anyGiverRevealed = (zone?.locations || []).some((l: any) =>
          (l.npcs || []).some((n: any) => n.role === 'quest_giver' && revealedNpcs.has(n.id))
        );
        const revealedQuests = anyGiverRevealed ? locQuests : [];

        const handleAccept = async (q: any) => {
          try {
            if (!playerId) throw new Error("Character not found.");
            const res = await fetch(`http://localhost:8000/quests/accept/${playerId}?quest_id=${q.id}`, { method: 'POST' });
            if (!res.ok) throw new Error("Could not accept quest");

            setPlayer((prev: any) => ({
              ...prev,
              active_quests: [...(prev.active_quests || []), { ...q, current_progress: 0 }]
            }));
            addLog(`Quest Accepted: ${q.title}`, "system");
            addLog(q.description, "system");
          } catch (err: any) {
            addLog(`Error supporting ${q.title}: ${err.message}`, "error");
          }
        };

        if (qFragment === 'all') {
          if (revealedQuests.length === 0) {
            addLog("No quests available to accept.", "error");
          } else {
            addLog(`Accepting all ${revealedQuests.length} available quests...`, "system");
            for (const q of revealedQuests) {
              await handleAccept(q);
            }
          }
        } else {
          let quest = null;
          const num = parseInt(qFragment);
          if (!isNaN(num) && num > 0 && num <= revealedQuests.length) {
            quest = revealedQuests[num - 1];
          } else if (qFragment === 'quest' || qFragment === '') {
            quest = revealedQuests[0];
          } else {
            quest = revealedQuests.find((q: any) => q.title.toLowerCase().includes(qFragment));
          }

          if (quest) {
            await handleAccept(quest);
          } else {
            addLog("No such quest available or revealed here.", "error");
            if (revealedQuests.length > 0) {
              addLog(`Revealed: ${revealedQuests.map((q: any, i: number) => `${i + 1}. ${q.title}`).join(", ")}`, "hint");
            }
          }
        }
      } else if (lowerCmd.startsWith('go ') || lowerCmd.startsWith('move ')) {
        const targetStr = lowerCmd.split(' ').slice(1).join(' ').trim();
        const currentLocation = zone?.locations?.find((l: any) => l.id === player?.current_location_id);

        let nextLocId = null;
        // Check for cardinal directions first
        if (currentLocation?.exits?.[targetStr]) {
          nextLocId = currentLocation.exits[targetStr];
        } else {
          // Fallback to searching by location name
          const nextLoc = zone?.locations?.find((l: any) =>
            l.name.toLowerCase().includes(targetStr) &&
            Object.values(currentLocation?.exits || {}).includes(l.id)
          );
          if (nextLoc) nextLocId = nextLoc.id;
        }

        if (nextLocId) {
          const nextLoc = zone.locations.find((l: any) => l.id === nextLocId);

          // Sync with backend — check for explore quest completions
          try {
            if (playerId) {
              const moveRes = await fetch(`http://localhost:8000/action/move/${playerId}?location_id=${nextLoc.id}`, { method: 'POST' });
              if (moveRes.ok) {
                const moveData = await moveRes.json();
                if (moveData.explore_completed?.length > 0) {
                  moveData.explore_completed.forEach((q: any) => {
                    addLog(`★ QUEST COMPLETE: "${q.title}"! Return to turn in.`, "system");
                  });
                  const completedIds = new Set(moveData.explore_completed.map((q: any) => q.id));
                  setPlayer((prev: any) => ({
                    ...prev,
                    active_quests: (prev.active_quests || []).map((q: any) =>
                      completedIds.has(q.id) ? { ...q, current_progress: 1, is_completed: true } : q
                    ),
                  }));
                }
              }
            }
          } catch (err) {
            console.error("Failed to sync movement:", err);
          }

          setPlayer((prev: any) => ({ ...prev, current_location_id: nextLoc.id }));
          setTarget(null);
          setAutoAttackTarget(null); // Cancel auto-attack on move
          setExploredLocations(prev => new Set(prev).add(nextLoc.id));
          addLog(`You travel to: ${nextLoc.name}`, "system");
          addLog(nextLoc.description, "system");
          // Forage hint on arrival
          const forageQ = (player?.active_quests || []).find((q: any) =>
            q.quest_type === 'forage' && q.target_id === nextLoc.id && !q.is_completed
          );
          if (forageQ) {
            addLog(`✦ ${forageQ.collect_name || "Resources"} can be gathered here (${forageQ.current_progress}/${forageQ.target_count}). Click GATHER or type 'gather'.`, "hint");
          }
          describeLocation(nextLoc.name, nextLoc.description, zone?.name || '');
          // Warn if there are live mobs here
          const nowArrival = Date.now() / 1000;
          const aliveMobsHere = (nextLoc.mobs || []).filter((m: any) => !m.respawn_at || m.respawn_at <= nowArrival);
          if (aliveMobsHere.length > 0) {
            const names = [...new Set(aliveMobsHere.map((m: any) => m.name))].join(', ');
            addLog(`⚔ Danger — ${names} lurk here. Type 'attack [name]' to engage.`, "combat");
          }
          if (nextLoc.npcs?.length > 0) {
            addLog("NPCS PRESENT:", "hint");
            nextLoc.npcs.forEach((n: any) => {
              if (n.role === 'vendor') addLog(`- ${n.name} (Merchant) — [shop]`, "hint");
              else if (n.role === 'quest_giver') addLog(`- ${n.name} (Quest Giver) — [talk to ${n.name}]`, "hint");
              else addLog(`- ${n.name}`, "hint");
            });
          }
        } else {
          addLog("You can't go there from here.", "error");
        }
      } else if (lowerCmd.startsWith('talk ') || lowerCmd.startsWith('interact ')) {
        const words = lowerCmd.split(' ');
        const targetName = words.length > 2 && (words[1] === 'to' || words[1] === 'with') ? words.slice(2).join(' ') : words.slice(1).join(' ');

        setIsTalking(true);
        try {
          if (!playerId) throw new Error("Character not found.");
          const res = await fetch(`http://localhost:8000/action/talk/${playerId}?npc_name=${targetName}`, { method: 'POST' });
          const data = await res.json();

          if (data.success) {
            describeEntity(data.npc_name, { isNpc: true });
            addLog(`${data.npc_name} says: "${data.dialogue}"`, "system");

            const loc = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
            const npc = loc?.npcs?.find((n: any) => n.name.toLowerCase().includes(targetName.toLowerCase()));

            if (npc?.role === 'quest_giver') {
              setRevealedNpcs(prev => new Set(prev).add(npc.id));

              // Use the backend-resolved quest list so we always show exactly what the NPC offers
              const offeredQuests: any[] = data.offered_quests ?? [];
              if (offeredQuests.length > 0) {
                addLog("── Available Quests ──────────────────", "system");
                offeredQuests.forEach((q: any, i: number) => {
                  addLog(`${i + 1}. [${q.title}] — ${q.objective}`, "hint");
                  addLog(`   ${q.description}  ·  Reward: ${q.xp_reward} XP`, "hint");
                });
                addLog("[accept all] ← click or type to accept every quest above", "hint");
              } else {
                addLog("All quests are already in progress or complete.", "hint");
              }
            }
          } else {
            addLog(data.message || "There's no one here by that name.", "error");
          }
        } catch (err: any) {
          addLog(`Dialogue Error: ${err.message}`, "error");
        } finally {
          setIsTalking(false);
        }
      } else if (lowerCmd.startsWith('track ')) {
        const qNum = parseInt(cmd.substring(6).trim());
        const activeQuests = player?.active_quests || [];
        const quest = !isNaN(qNum) && qNum > 0 && qNum <= activeQuests.length ? activeQuests[qNum - 1] : null;

        if (quest) {
          const targetLoc = zone?.locations?.find((l: any) => l.mobs?.some((m: string) => m.toLowerCase().includes(quest.target_id.toLowerCase())) || l.npcs?.some((n: any) => n.id === quest.target_id));
          if (targetLoc) {
            const currentLoc = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
            const direction = Object.entries(currentLoc?.exits || {}).find(([dir, id]) => id === targetLoc.id)?.[0];
            if (direction) {
              addLog(`Tracking ${quest.title}: Your objective is to the ${direction.toUpperCase()}.`, "hint");
            } else if (targetLoc.id === currentLoc.id) {
              addLog(`Tracking ${quest.title}: You are already at the objective location!`, "hint");
            } else {
              addLog(`Tracking ${quest.title}: The objective is further away. Try exploring nearby locations.`, "hint");
            }
          } else {
            addLog(`Tracking ${quest.title}: Your senses are unclear about where to find ${quest.target_id}.`, "hint");
          }
        } else {
          addLog("Which quest do you want to track? Type 'track [number from your log]'.", "error");
        }
      } else if (lowerCmd.startsWith('kill ') || lowerCmd.startsWith('attack ')) {
        const targetStr = lowerCmd.split(' ').slice(1).join(' ').trim();
        const loc = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
        const nowTs = Date.now() / 1000;
        const mob = loc?.mobs?.find((m: any) =>
          m.name.toLowerCase().includes(targetStr) && (!m.respawn_at || m.respawn_at <= nowTs)
        );

        if (mob) {
          try {
            if (!playerId) throw new Error("Character not found.");

            setIsAttacking(true);
            setLastCombatTime(Date.now());

            const res = await fetch(
              `http://localhost:8000/action/attack/${playerId}?mob_name=${encodeURIComponent(targetStr)}`,
              { method: 'POST' }
            );
            const data = await res.json();
            setIsAttacking(false);

            if (!data.success) {
              // Cooldown rejection from backend — just wait silently, auto-attack will retry
              if (!data.on_cooldown) addLog(data.message, "error");
              return;
            }

            // Describe entity the first time we engage this mob
            if (!target || target.name !== data.target_name) {
              if (data.consider) addLog(`You size up the ${data.target_name}: ${data.consider}`, "hint");
              describeEntity(data.target_name, { isElite: data.target_is_elite, isNamed: data.target_is_named });
            }

            // Elite/Named announcement
            const nameplate = data.target_is_named ? "⚑ NAMED" : data.target_is_elite ? "★ ELITE" : "";
            setTarget((prev: any) => {
              if (prev?.name !== data.target_name) {
                const cached = entityDescCache.current.get(data.target_name);
                setTargetDescription(cached ?? '');
              }
              return prev;
            });
            setTarget({
              name: data.target_name,
              hp: data.mob_hp,
              max_hp: data.target_max_hp,
              level: data.target_level,
              is_elite: data.target_is_elite,
              is_named: data.target_is_named,
            });

            // Staggered combat messages — proc messages (★) shown as gold "player" type
            data.messages.forEach((msg: string, idx: number) => {
              const msgType = msg.includes("★") ? "player"
                : msg.includes("⬆") || msg.includes("⚑") ? "system"
                : /^\+\d+ gold/i.test(msg) ? "system"
                : "combat";
              setTimeout(() => addLog(msg, msgType), idx * 250);
            });
            // Progression milestone hints on level-up
            if (data.player_level && data.player_level !== player?.level) {
              const delay = data.messages.length * 250 + 100;
              if (data.player_level === 10) {
                setTimeout(() => addLog("⚑ DUNGEONS UNLOCKED — type 'travel dungeon' or use the sidebar to enter.", "hint"), delay);
              } else if (data.player_level === 20) {
                setTimeout(() => addLog("⚑ RAIDS UNLOCKED — type 'travel raid' or use the sidebar to enter.", "hint"), delay);
              }
            }

            setLastCombatTime(Date.now());
            if (data.player_hp < (player?.hp ?? data.player_hp)) {
              setCombatFlash(true);
              setTimeout(() => setCombatFlash(false), 200);
            }

            const delay = data.messages.length * 250;
            setTimeout(async () => {
              // Compute quest updates outside setPlayer to avoid double-logging in StrictMode
              const questLogs: Array<{ msg: string; type: 'system' | 'hint' }> = [];
              if (data.target_dead) {
                (player?.active_quests || []).forEach((q: any) => {
                  const newProg = questNewProgress(q, targetStr, data.target_is_named, data.target_is_elite);
                  if (newProg === null) return;
                  if (newProg >= q.target_count && !q.is_completed) {
                    questLogs.push({ msg: `★ QUEST COMPLETE: "${q.title}"! Return to turn in.`, type: 'system' });
                  } else {
                    questLogs.push({ msg: `${q.title}: ${newProg}/${q.target_count}`, type: 'hint' });
                  }
                });
                questLogs.forEach(l => addLog(l.msg, l.type));
              }

              setPlayer((prev: any) => {
                if (!prev) return prev;
                let updatedQuests    = prev.active_quests || [];
                let updatedInventory = prev.inventory || [];
                let updatedEquipment = prev.equipment || {};

                if (data.target_dead) {
                  updatedQuests = updatedQuests.map((q: any) => {
                    const newProg = questNewProgress(q, targetStr, data.target_is_named, data.target_is_elite);
                    if (newProg === null) return q;
                    return { ...q, current_progress: newProg, is_completed: newProg >= q.target_count };
                  });

                  if (data.loot_item) {
                    if (data.auto_equipped && data.loot_item.slot) {
                      // Backend auto-equipped it — update equipment slot
                      updatedEquipment = { ...updatedEquipment, [data.loot_item.slot]: data.loot_item };
                      // Add displaced item to inventory if there was one
                      if (data.displaced_item) {
                        updatedInventory = [...updatedInventory, data.displaced_item];
                      }
                    } else {
                      updatedInventory = [...updatedInventory, data.loot_item];
                    }
                    setActiveLoot(data.loot_item);
                    setTimeout(() => setActiveLoot(null), 5000);
                  }
                }

                const hpUpdate = data.player_dead
                  ? { hp: data.player_hp, current_location_id: data.respawn_location_id ?? prev.current_location_id }
                  : { hp: data.player_hp };

                // Drain rested XP pool from local state
                if (data.rested_bonus > 0) {
                  setRestedXp(data.rested_xp ?? 0);
                }

                return {
                  ...prev,
                  ...hpUpdate,
                  max_hp:         data.player_max_hp        ?? prev.max_hp,
                  level:          data.player_level         ?? prev.level,
                  damage:         data.player_damage        ?? prev.damage,
                  next_level_xp:  data.player_next_level_xp ?? prev.next_level_xp,
                  xp:        data.player_xp ?? (prev.xp + (data.xp_gained || 0)),
                  gold:      data.player_gold ?? (prev.gold || 0) + (data.gold_gained || 0),
                  kills:     data.player_kills ?? (prev.kills || 0),
                  equipment: updatedEquipment,
                  active_quests: updatedQuests,
                  inventory:     updatedInventory,
                };
              });

              if (data.target_dead) {
                const restedTag = data.rested_bonus > 0 ? ` 💤(+${data.rested_bonus} rested)` : '';
                const killLine = `${nameplate ? nameplate + ' ' : ''}${data.target_name} slain. +${data.xp_gained} XP${restedTag}${data.gold_gained ? ` +${data.gold_gained}g` : ''}`;
                addLog(killLine, "system");
                // Abort any in-flight idle chat so LM Studio can start the death description immediately
                idleChatAbortRef.current?.abort();
                idleChatAbortRef.current = null;
                describeEntity(data.target_name, { isElite: data.target_is_elite, isNamed: data.target_is_named, isDeath: true });

                // Stop auto-attack & clear target
                setAutoAttackTarget(null);
                setTarget(null);

                // Mark mob dead locally
                setZone((prev: any) => ({
                  ...prev,
                  locations: (prev.locations || []).map((l: any) =>
                    l.id !== player?.current_location_id ? l : {
                      ...l,
                      mobs: l.mobs.map((m: any) =>
                        m.name.toLowerCase().includes(targetStr.toLowerCase()) && (!m.respawn_at || m.respawn_at <= nowTs)
                          ? { ...m, hp: 0, respawn_at: data.mob_respawn_at ?? nowTs + 34 }
                          : m
                      )
                    }
                  )
                }));

                // Sync quest progress to backend
                (player?.active_quests || []).forEach(async (q: any) => {
                  const newProg = questNewProgress(q, targetStr, data.target_is_named, data.target_is_elite);
                  if (newProg === null) return;
                  try { await fetch(`http://localhost:8000/quests/progress/${playerId}?quest_id=${q.id}&progress=${newProg}`, { method: 'POST' }); } catch {}
                });

              } else {
                // Mob survived — update its HP locally (matches what backend saved)
                setZone((prev: any) => ({
                  ...prev,
                  locations: (prev.locations || []).map((l: any) =>
                    l.id !== player?.current_location_id ? l : {
                      ...l,
                      mobs: l.mobs.map((m: any) =>
                        m.name.toLowerCase().includes(targetStr.toLowerCase()) && (!m.respawn_at || m.respawn_at <= nowTs)
                          ? { ...m, hp: data.mob_hp }
                          : m
                      )
                    }
                  )
                }));

                // Continue auto-attack
                setAutoAttackTarget(targetStr);
              }

              if (data.player_dead) {
                describeEntity(data.target_name, { isElite: data.target_is_elite, isNamed: data.target_is_named, isDeath: true });
                addLog("☠ You have been defeated! You wake at the settlement.", "error");
                setAutoAttackTarget(null);
                setTarget(null);
                // Auto-describe the respawn location
                const respawnLoc = zone?.locations?.find((l: any) => l.id === data.respawn_location_id);
                if (respawnLoc) {
                  setTimeout(() => {
                    addLog("─────────────────────────────────────", "system");
                    addLog(`📍 ${respawnLoc.name}`, "system");
                    addLog(respawnLoc.description, "hint");
                    const npcsHere = (respawnLoc.npcs || []).map((n: any) => n.name).join(', ');
                    if (npcsHere) addLog(`Present: ${npcsHere}`, "hint");
                  }, 400);
                }
              }

              // Sync gear score after level-up or auto-equip
              if (data.gear_score != null) setGearScore(data.gear_score);

              // Sync potion cooldowns + XP buff from authoritative backend values
              if (data.heal_cd !== undefined) setHealCd(data.heal_cd);
              if (data.xp_cd   !== undefined) setXpCd(data.xp_cd);
              if (data.active_xp_buff !== undefined) setActiveXpBuff(data.active_xp_buff ?? null);

              // Auto-use healing potion at ≤ 25 % HP
              const lowHp = !data.player_dead && data.player_hp <= Math.floor((data.player_max_hp || 1) * 0.25);
              if (lowHp && data.heal_cd === 0) {
                const healPot = (player?.inventory || []).find((i: any) => i.slot === 'consumable' && i.stats?.heal_pct);
                if (healPot) {
                  addLog('⚡ AUTO: Healing Potion used!', 'system');
                  usePotion(healPot.id, true);
                }
              }
            }, delay);

          } catch (err: any) {
            setIsAttacking(false);
            addLog(`Combat Error: ${err.message}`, "error");
          }
        } else {
          const deadMob = loc?.mobs?.find((m: any) =>
            m.name.toLowerCase().includes(targetStr) && m.respawn_at && m.respawn_at > nowTs
          );
          if (deadMob) {
            addLog(`The ${deadMob.name} is dead. Respawn in ~${Math.ceil(deadMob.respawn_at - nowTs)}s.`, "hint");
          } else {
            addLog("There is no such creature here to attack.", "error");
          }
          setAutoAttackTarget(null);
          setTarget(null);
        }
      } else if (lowerCmd.startsWith('use ')) {
        const itemName = lowerCmd.slice(4).trim();
        const item = (player?.inventory || []).find((i: any) =>
          i.slot === 'consumable' && i.name.toLowerCase().includes(itemName)
        );
        if (!item) {
          addLog(`No consumable matching "${itemName}" in your bag.`, 'error');
        } else {
          await usePotion(item.id);
        }
      } else if (lowerCmd === 'inv' || lowerCmd === 'inventory') {
        const inv = player?.inventory || [];
        if (inv.length > 0) {
          addLog("--- INVENTORY ---", "system");
          inv.forEach((item: any, idx: number) => {
            const statStr = item.stats ? Object.entries(item.stats).map(([k, v]) => `+${v} ${k}`).join(', ') : '';
            const equipped = item.slot ? player?.equipment?.[item.slot] : null;
            const equippedSum = equipped?.stats ? Object.values(equipped.stats as Record<string,number>).reduce((a,b)=>a+b,0) : 0;
            const newSum = item.stats ? Object.values(item.stats as Record<string,number>).reduce((a,b)=>a+b,0) : 0;
            const delta = newSum - equippedSum;
            const statKey = Object.keys(item.stats||{})[0]||'stat';
            const cmp = equipped && equipped.name !== 'None'
              ? (delta > 0 ? ` ▲+${delta} ${statKey}` : delta < 0 ? ` ▼${delta} ${statKey}` : ' =')
              : equipped ? ' [empty slot]' : '';
            addLog(`${idx + 1}. [${item.name}] (${item.rarity})${statStr ? ` — ${statStr}` : ''}${cmp}`, "system");
          });
          addLog("HINT: Type 'equip [number]' or click a bag slot to equip.", "hint");
        } else {
          addLog("Your bags are empty.", "system");
        }

      } else if (lowerCmd.startsWith('equip ')) {
        const arg = cmd.substring(6).trim(); // preserve original case for IDs
        const inv = player?.inventory || [];
        let item: any = null;
        const num = parseInt(arg);
        if (!isNaN(num) && num > 0 && num <= inv.length) {
          item = inv[num - 1];
        } else {
          // Try exact ID match first (from click-to-equip), then fuzzy name match
          item = inv.find((i: any) => i.id === arg)
              ?? inv.find((i: any) => i.name.toLowerCase().includes(arg.toLowerCase()));
        }

        // If not in inventory, check if it's already equipped (e.g. auto-equipped on drop)
        if (!item) {
          const equippedEntries = Object.entries(player?.equipment || {});
          const alreadyEquipped = equippedEntries.find(([, eq]: any) =>
            eq?.name && eq.name.toLowerCase().includes(arg)
          );
          if (alreadyEquipped) {
            const [slot, eq]: any = alreadyEquipped;
            const statStr = eq.stats ? Object.entries(eq.stats).map(([k, v]) => `+${v} ${k}`).join(', ') : '';
            addLog(`[${eq.name}] is already equipped in ${slot.replace('_', ' ')}. ${statStr}`, "hint");
            return;
          }
          addLog("No such item in your inventory. Type 'inventory' to see your items.", "error");
        } else if (!playerId) {
          addLog("Character not found.", "error");
        } else {
          try {
            const res = await fetch(`http://localhost:8000/action/equip/${playerId}?item_id=${item.id}`, { method: 'POST' });
            const data = await res.json();
            if (!res.ok) {
              addLog(data.detail || "Could not equip that item.", "error");
            } else if (data.success) {
              const statStr = item.stats ? Object.entries(item.stats).map(([k, v]) => `+${v} ${k}`).join(', ') : '';
              addLog(`Equipped [${item.name}] to ${data.slot.replace('_', ' ')}. ${statStr}`, "system");
              if (data.gear_score != null) setGearScore(data.gear_score);
              // Also add back any displaced item that backend swapped out
              setPlayer((prev: any) => {
                const displaced = prev.equipment?.[data.slot];
                const newInv = prev.inventory.filter((i: any) => i.id !== item.id);
                if (displaced && displaced.name !== 'None') newInv.push(displaced);
                return {
                  ...prev,
                  equipment: { ...prev.equipment, [data.slot]: data.equipped },
                  inventory: newInv,
                };
              });
            } else {
              addLog(data.detail || "Could not equip that item.", "error");
            }
          } catch (err: any) {
            addLog(`Equip Error: ${err.message}`, "error");
          }
        }

      } else if (lowerCmd.startsWith('unequip ') || lowerCmd === 'unequip') {
        const slotArg = lowerCmd.replace('unequip', '').trim().replace(' ', '_');
        const validSlots = ['head','chest','hands','legs','feet','main_hand','off_hand'];
        const slot = validSlots.find(s => s === slotArg || s.replace('_',' ') === slotArg);
        if (!slot) {
          addLog(`Specify a slot: ${validSlots.map(s => s.replace('_',' ')).join(', ')}`, "hint");
        } else if (!playerId) {
          addLog("Character not found.", "error");
        } else {
          try {
            const res = await fetch(`http://localhost:8000/action/unequip/${playerId}?slot=${slot}`, { method: 'POST' });
            const data = await res.json();
            if (!res.ok) { addLog(data.detail || "Nothing equipped there.", "error"); }
            else if (data.success) {
              addLog(`Unequipped [${data.unequipped.name}] from ${slot.replace('_',' ')} → moved to bag.`, "system");
              if (data.gear_score != null) setGearScore(data.gear_score);
              setPlayer((prev: any) => ({
                ...prev,
                equipment: { ...prev.equipment, [slot]: { name: 'None' } },
                inventory: [...(prev.inventory || []), data.unequipped],
              }));
            }
          } catch (err: any) { addLog(`Unequip Error: ${err.message}`, "error"); }
        }

      } else if (lowerCmd === 'turnin' || lowerCmd === 'turn in' || lowerCmd === 'complete quest') {
        const loc = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
        const hasQuestGiver = loc?.npcs?.some((n: any) => n.role === 'quest_giver');
        if (!hasQuestGiver) {
          addLog("There is no quest giver here. Return to the settlement to turn in quests.", "hint");
        } else {
          const completedQuests = (player?.active_quests || []).filter((q: any) => q.is_completed);
          if (completedQuests.length === 0) {
            addLog("You have no completed quests to turn in.", "hint");
          } else {
            const turnedInIds: string[] = [];
            for (const quest of completedQuests) {
              try {
                const res = await fetch(`http://localhost:8000/quests/complete/${playerId}?quest_id=${quest.id}`, { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                  turnedInIds.push(quest.id);
                  data.messages.forEach((msg: string) => addLog(msg, "system"));
                  setPlayer((prev: any) => {
                    const newCompleted = [...(prev.completed_quest_ids || []), quest.id];
                    const remaining = prev.active_quests.filter((q: any) => q.id !== quest.id);
                    // item_placement tells us where the item ended up: inventory | equipped | dropped
                    const placement = data.item_placement;
                    const updatedInv = placement === 'inventory' && data.item_reward
                      ? [...prev.inventory, data.item_reward]
                      : prev.inventory;
                    const updatedEquip = placement === 'equipped' && data.item_reward && data.equipped_slot
                      ? { ...prev.equipment, [data.equipped_slot]: data.item_reward }
                      : prev.equipment;
                    return {
                      ...prev,
                      xp:            data.new_xp,
                      level:         data.new_level,
                      next_level_xp: data.new_next_level_xp ?? prev.next_level_xp,
                      max_hp:        data.new_max_hp        ?? prev.max_hp,
                      active_quests: remaining,
                      completed_quest_ids: newCompleted,
                      inventory: updatedInv,
                      equipment: updatedEquip,
                    };
                  });
                  if (data.gear_score != null) setGearScore(data.gear_score);
                  if (data.item_reward && data.item_placement !== 'dropped') {
                    setActiveLoot(data.item_reward);
                    setTimeout(() => setActiveLoot(null), 5000);
                  }
                }
              } catch (err: any) {
                addLog(`Turn-in Error: ${err.message}`, "error");
              }
            }
          }
        }

      } else if (lowerCmd === 'gather' || lowerCmd === 'forage' || lowerCmd === 'search') {
        if (!playerId) return;
        if (isGathering) { addLog("Already gathering...", "hint"); return; }

        // Auto-gather loop — one press gathers everything until quest complete
        setIsGathering(true);
        (async () => {
          const GATHER_CD = 8000;
          try {
            while (true) {
              const res = await fetch(`http://localhost:8000/action/gather/${playerId}`, { method: 'POST' });
              const data = await res.json();

              if (!data.success) {
                addLog(data.message, data.interrupted ? "error" : "hint");
                break;
              }

              data.messages?.forEach((msg: string) => addLog(msg, "system"));

              let allDone = false;
              if (data.quest_updates?.length) {
                setPlayer((prev: any) => {
                  if (!prev) return prev;
                  const updatedQuests = prev.active_quests.map((q: any) => {
                    const upd = data.quest_updates.find((u: any) => u.id === q.id);
                    return upd ? { ...q, current_progress: upd.progress, is_completed: upd.completed } : q;
                  });
                  return { ...prev, active_quests: updatedQuests };
                });
                allDone = data.quest_updates.every((u: any) => u.completed);
              }

              if (allDone) break;

              // Show cooldown in chat and animate the progress bar
              const resource = data.quest_updates?.[0]
                ? (player?.active_quests || []).find((q: any) => q.id === data.quest_updates[0].id)?.collect_name || "resources"
                : "resources";
              addLog(`Searching for ${resource}... (${GATHER_CD / 1000}s)`, "hint");
              await new Promise<void>(resolve => {
                const start = Date.now();
                const tick = () => {
                  const elapsed = Date.now() - start;
                  const pct = Math.min(100, (elapsed / GATHER_CD) * 100);
                  // Drive bar directly via DOM to avoid React transition lag
                  if (gatherBarRef.current) gatherBarRef.current.style.width = `${pct}%`;
                  setGatherCooldown(pct); // updates the text label only
                  if (pct < 100) requestAnimationFrame(tick);
                  else { setGatherCooldown(0); resolve(); }
                };
                requestAnimationFrame(tick);
              });
            }
          } catch (err: any) {
            addLog(`Gather Error: ${err.message}`, "error");
          } finally {
            setIsGathering(false);
            setGatherCooldown(0);
          }
        })();

      } else if (lowerCmd === 'advance' || lowerCmd === 'next room') {
        if (!dungeonRun) {
          addLog("You are not in a dungeon.", "hint");
        } else {
          const advRun = dungeonRun;
          const advRoom = advRun.rooms?.[advRun.room_index];
          if (!advRoom?.cleared && (advRoom?.mobs || []).some((m: any) => m.hp > 0)) {
            addLog("Clear all enemies before advancing.", "error");
          } else if (advRun.room_index >= (advRun.rooms?.length ?? 1) - 1) {
            addLog("Already in the final room.", "hint");
          } else {
            const res = await fetch(`http://localhost:8000/dungeon/advance/${advRun.id}?player_id=${playerId}`, { method: 'POST' });
            if (res.ok) {
              const d = await res.json();
              setDungeonRun(d);
              addLog(`→ Entering ${d.rooms?.[d.room_index]?.name}...`, 'system');
            }
          }
        }

      } else if (lowerCmd === 'flee' || lowerCmd === 'escape' || lowerCmd === 'disengage') {
        // In dungeon mode: flee exits the dungeon instance
        if (dungeonRun) {
          await fetch(`http://localhost:8000/dungeon/flee/${dungeonRun.id}?player_id=${playerId}`, { method: 'POST' }).catch(() => {});
          setDungeonRun(null);
          addLog('You flee the dungeon.', 'system');
        } else if (!autoAttackTarget) {
          addLog("You are not in combat.", "hint");
        } else {
          const fleeMob = autoAttackTarget;
          try {
            if (!playerId) throw new Error("Character not found.");
            const res = await fetch(
              `http://localhost:8000/action/flee/${playerId}?mob_name=${encodeURIComponent(fleeMob)}`,
              { method: 'POST' }
            );
            const data = await res.json();
            data.messages?.forEach((msg: string) => addLog(msg, data.fled ? "system" : "combat"));
            if (data.fled || data.player_dead) {
              setAutoAttackTarget(null);
              setTarget(null);
            }
            setPlayer((prev: any) => ({
              ...prev,
              hp: data.player_hp ?? prev.hp,
              xp: data.player_xp ?? prev.xp,
              ...(data.player_dead && data.respawn_location_id
                ? { current_location_id: data.respawn_location_id }
                : {}),
            }));
            if (data.player_dead) {
              describeEntity(fleeMob || 'the enemy', { isDeath: true });
              addLog("☠ Slain while fleeing! You wake at the settlement.", "error");
            }
          } catch (err: any) {
            addLog(`Flee Error: ${err.message}`, "error");
          }
        }

      } else if (lowerCmd === 'shop' || lowerCmd === 'browse') {
        const loc = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
        const vendor = loc?.npcs?.find((n: any) => n.role === 'vendor');
        if (!vendor) {
          addLog("There is no merchant here. Visit a hub settlement.", "hint");
        } else {
          // Show vendor greeting/dialogue
          if (vendor.dialogue) addLog(`${vendor.name}: "${vendor.dialogue}"`, "system");
          addLog(`--- ${vendor.name}'s Shop --- (Gold: ${player?.gold || 0}g)`, "system");
          if (!vendor.vendor_items?.length) {
            addLog("No stock available.", "hint");
          } else {
            vendor.vendor_items.forEach((item: any, idx: number) => {
              const statStr = item.stats ? Object.entries(item.stats).map(([k, v]) => `+${v} ${k}`).join(', ') : '';
              const canAfford = (player?.gold || 0) >= item.price;
              addLog(
                `${idx + 1}. [${item.name}] — ${item.rarity} · ${statStr} · ${item.price}g${canAfford ? '' : ' (need more gold)'}`,
                canAfford ? "hint" : "error"
              );
            });
            addLog("Type 'buy [number]' to purchase.", "hint");
          }
          // Sell section
          const sellable = (player?.inventory || []);
          if (sellable.length > 0) {
            addLog("── Your Bag (sell for ~40% value) ──────", "system");
            sellable.forEach((item: any, idx: number) => {
              const statStr = item.stats ? Object.entries(item.stats).map(([k, v]) => `+${v} ${k}`).join(', ') : '';
              const statTotal = item.stats ? Object.values(item.stats as Record<string, number>).reduce((a: number, b: number) => a + b, 0) : 0;
              const sellPrice = Math.max(1, Math.floor((item.level || 1) * statTotal * 0.8));
              addLog(`${idx + 1}. [sell ${item.name}] — ${item.rarity} · ${statStr} · sells for ~${sellPrice}g`, "hint");
            });
          }
        }

      } else if (lowerCmd.startsWith('buy ')) {
        const arg = lowerCmd.substring(4).trim();
        const loc = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
        const vendor = loc?.npcs?.find((n: any) => n.role === 'vendor');
        if (!vendor) {
          addLog("No merchant here.", "error");
        } else if (!playerId) {
          addLog("Character not found.", "error");
        } else {
          const num = parseInt(arg);
          const itemData = !isNaN(num) && num > 0
            ? vendor.vendor_items?.[num - 1]
            : vendor.vendor_items?.find((i: any) => i.name.toLowerCase().includes(arg));
          if (!itemData) {
            addLog("No such item at this merchant.", "error");
          } else if ((player?.gold || 0) < itemData.price) {
            addLog(`Not enough gold. Need ${itemData.price}g, you have ${player?.gold || 0}g.`, "error");
          } else {
            try {
              const res = await fetch(
                `http://localhost:8000/vendor/buy/${playerId}?npc_name=${encodeURIComponent(vendor.name)}&item_id=${itemData.id}`,
                { method: 'POST' }
              );
              const data = await res.json();
              if (data.success) {
                addLog(data.message, "system");
                setPlayer((prev: any) => ({
                  ...prev,
                  gold: data.player_gold,
                  inventory: [...(prev.inventory || []), data.item],
                }));
                setActiveLoot(data.item);
                setTimeout(() => setActiveLoot(null), 5000);
              } else {
                addLog(data.message || "Purchase failed.", "error");
              }
            } catch (err: any) {
              addLog(`Buy Error: ${err.message}`, "error");
            }
          }
        }

      } else if (lowerCmd === 'sell') {
        // No argument — list inventory with sell prices
        const loc = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
        const hasVendor = loc?.npcs?.some((n: any) => n.role === 'vendor');
        if (!hasVendor) { addLog("No merchant here to sell to.", "error"); }
        else {
          const inv = player?.inventory || [];
          if (!inv.length) { addLog("Your bag is empty.", "hint"); }
          else {
            addLog("── Sell Items ──────────────────────────", "system");
            inv.forEach((item: any, idx: number) => {
              const statStr = item.stats ? Object.entries(item.stats).map(([k, v]) => `+${v} ${k}`).join(', ') : '';
              const statTotal = item.stats ? Object.values(item.stats as Record<string, number>).reduce((a: number, b: number) => a + b, 0) : 0;
              const sellPrice = Math.max(1, Math.floor((item.level || 1) * statTotal * 0.8));
              addLog(`${idx + 1}. [sell ${item.name}] — ${item.rarity} · ${statStr} · ~${sellPrice}g`, "hint");
            });
          }
        }

      } else if (lowerCmd === 'sell junk' || lowerCmd === 'sell all') {
        const sjLoc = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
        if (!sjLoc?.npcs?.some((n: any) => n.role === 'vendor')) {
          addLog("No merchant here to sell to.", "error");
        } else if (!playerId) { addLog("Character not found.", "error"); }
        else {
          try {
            const res = await fetch(`http://localhost:8000/vendor/sell_junk/${playerId}`, { method: 'POST' });
            const data = await res.json();
            addLog(data.message, data.sold_count > 0 ? "system" : "hint");
            if (data.sold_count > 0) {
              setPlayer((prev: any) => ({
                ...prev,
                gold: data.player_gold,
                inventory: (prev.inventory || []).filter((i: any) => i.rarity !== "Common" || i.slot === "consumable"),
              }));
            }
          } catch (err: any) { addLog(`Sell Error: ${err.message}`, "error"); }
        }

      } else if (lowerCmd.startsWith('sell ')) {
        const arg = lowerCmd.substring(5).trim();
        const loc = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
        const hasVendor = loc?.npcs?.some((n: any) => n.role === 'vendor');
        if (!hasVendor) {
          addLog("No merchant here to sell to.", "error");
        } else if (!playerId) {
          addLog("Character not found.", "error");
        } else {
          const inv = player?.inventory || [];
          const num = parseInt(arg);
          const item = !isNaN(num) && num > 0 && num <= inv.length
            ? inv[num - 1]
            : inv.find((i: any) => i.name.toLowerCase().includes(arg));
          if (!item) {
            addLog("No such item in your inventory.", "error");
          } else {
            try {
              const res = await fetch(
                `http://localhost:8000/vendor/sell/${playerId}?item_id=${item.id}`,
                { method: 'POST' }
              );
              const data = await res.json();
              if (data.success) {
                addLog(data.message, "system");
                setPlayer((prev: any) => ({
                  ...prev,
                  gold: data.player_gold,
                  inventory: prev.inventory.filter((i: any) => i.id !== item.id),
                }));
              } else {
                addLog(data.message || "Sale failed.", "error");
              }
            } catch (err: any) {
              addLog(`Sell Error: ${err.message}`, "error");
            }
          }
        }

      } else if (lowerCmd === 'travel' || lowerCmd === 'next zone' || lowerCmd.startsWith('travel ')) {
        const isDungeon = lowerCmd.includes('dungeon');
        const isRaid    = lowerCmd.includes('raid');
        const zoneType  = isRaid ? 'Raid' : isDungeon ? 'Dungeon' : 'Zone';

        // Dungeons and raids use the instanced dungeon engine, not zone travel
        if (isDungeon || isRaid) {
          addLog(`Assembling ${isRaid ? '10-player raid' : '5-player dungeon'} party...`, "system");
          try {
            if (!playerId) throw new Error("Character not found.");
            const res = await fetch(
              `http://localhost:8000/dungeon/enter/${playerId}?is_raid=${isRaid}`,
              { method: 'POST' }
            );
            if (!res.ok) {
              const err = await res.json();
              addLog(err.detail || "Cannot enter dungeon yet.", "error");
            } else {
              const run = await res.json();
              setDungeonRun(run);
              const firstRoom = run.rooms?.[0];
              addLog(`━━━ ENTERING: ${run.dungeon_name?.toUpperCase()} ━━━`, "system");
              addLog(`Your party assembles: ${(run.party || []).map((m: any) => `${m.name} (${m.char_class})`).join(', ')}`, "hint");
              addLog(`Room 1: ${firstRoom?.name} — ${firstRoom?.mobs?.length} enemies ahead.`, "hint");
            }
          } catch (err: any) {
            addLog(`Dungeon Error: ${err.message}`, "error");
          }
          return;
        }

        // Show gear score progress before attempting open-world travel
        if (!isDungeon && !isRaid) {
          const zoneMaxLevel = Math.max(...(zone?.level_range || [1, 5]));
          const requiredGs = zoneMaxLevel * 25;
          const currentGs = gearScore ?? 0;
          if (currentGs < requiredGs) {
            addLog(`Gear score: ${currentGs} / ${requiredGs} required — run dungeons and raids to earn better gear first.`, "hint");
          }
        }
        addLog(`Generating new ${zoneType}... Please wait.`, "system");
        try {
          if (!playerId) throw new Error("Character not found.");
          const res = await fetch(
            `http://localhost:8000/zone/travel/${playerId}?is_dungeon=false&is_raid=false`,
            { method: 'POST' }
          );
          if (!res.ok) {
            const err = await res.json();
            addLog(err.detail || "Cannot travel there yet.", "error");
            // Show gear score progress hint if it's a GS block
            if (err.detail?.includes('Gear score')) {
              addLog(`Your gear score: ${gearScore ?? 0}  ·  Run dungeons and raids to earn better drops.`, "hint");
            }
          } else {
            const data = await res.json();
            const newZone = data.zone;
            addLog("★ ZONE CLEARED! Advancing to the next challenge.", "system");
            setZone(newZone);
            setPlayer((prev: any) => ({
              ...prev,
              current_zone_id: newZone.id,
              current_location_id: newZone.locations?.[0]?.id ?? prev.current_location_id,
            }));
            setChatSummary("");
            chatMsgCountRef.current = 0;
            setTarget(null);
            const hub = newZone.locations?.[0];
            addLog(`━━━ ENTERING: ${newZone.name.toUpperCase()} ━━━`, "system");
            addLog(newZone.description, "system");
            if (hub) {
              addLog(`You arrive at: ${hub.name}`, "system");
              addLog(hub.description, "system");
              describeLocation(hub.name, hub.description, newZone.name);
              if (hub.npcs?.length > 0) {
                addLog("PEOPLE HERE:", "hint");
                hub.npcs.forEach((n: any) => addLog(`- ${n.name} (${n.role})`, "hint"));
              }
            }
            addLog(`HINT: Type 'talk to [npc name]' to get quests, or 'look' to survey the area.`, "hint");
          }
        } catch (err: any) {
          addLog(`Travel Error: ${err.message}`, "error");
        }

      } else {
        // AI Narrative Fallback
        try {
          if (!playerId) throw new Error("Character not found.");
          const res = await fetch(`http://localhost:8000/narrative/stream/${playerId}?action=${encodeURIComponent(cmd)}`);
          if (!res.ok) throw new Error("Engine busy.");

          const reader = res.body?.getReader();
          if (!reader) throw new Error("No stream");

          let narrativeText = "";
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const chunk = new TextDecoder().decode(value);
            narrativeText += chunk;
            // Update the last log entry or append as it comes
          }
          addLog(narrativeText, "system");
        } catch (err: any) {
          addLog(`The engine hums... but your command '${cmd}' yields no immediate result.`, "error");
          addLog("Try: 'look', 'quests', 'go [direction]', 'talk to [npc]'.", "hint");
        }
      }
    }
  };

  return (
    <main className="mud-container">
      {renderTargetFrame()}
      {/* Cinematic Header Overlay */}
      {step === 'game' && (
        <header className="stats-bar-wrapper">
          <div className="glass-panel stats-panel">
            <div className="unit-frame">
              <div className={`portrait-box glow-${player?.char_class?.toLowerCase() || 'default'}`}>
                <img
                  src={`/assets/portraits/${player?.char_class?.toLowerCase() || 'default'}.png`}
                  alt="Portrait"
                  className="portrait-img"
                />
              </div>
              <div className="unit-info">
                <div className="unit-name text-accent font-bold tracking-widest">{player?.name || "ARCHETYPAL ENTITY"}</div>
                <div className="unit-class text-[10px] opacity-40 uppercase tracking-widest">{player ? `${player.race} ${player.char_class}  ·  Level ${player.level}` : "Initializing..."}</div>
                <div className="hud-location">
                  <span className="location-name">{zone?.locations?.find((l: any) => l.id === player?.current_location_id)?.name || "The Void"}</span>
                </div>
              </div>
            </div>

            <div className="branding-center">
              <img 
                src="/assets/ui/logo.png" 
                alt="SINGLE PLAYER AI MUD" 
                className="game-logo"
              />
              <div className="dev-credit">developed by Ocean Bennett</div>
            </div>

            <div className="stats-group">
              <div className="stat-item">
                <div className="stat-header">
                  <span className="stat-label">HP</span>
                  <span className="stat-value">{player?.hp || 100} / {player?.max_hp || 100}</span>
                </div>
                <div className="progress-container">
                  <div className="progress-fill hp-fill" style={{ width: `${((player?.hp || 100) / (player?.max_hp || 100)) * 100}%` }}>
                    <div className="progress-shine" />
                  </div>
                </div>
              </div>

              <div className="stat-item">
                <div className="stat-header">
                  <span className="stat-label">GOLD</span>
                  <span className="stat-value text-yellow-400">⬡ {player?.gold || 0}</span>
                </div>
                <div className="stat-header mt-1">
                  <span className="stat-label">KILLS</span>
                  <span className="stat-value">{player?.kills || 0}</span>
                </div>
                <div className="stat-header mt-1">
                  <span className="stat-label">
                    GS
                    <span className="text-[9px] opacity-40 ml-1">{gearScore < 100 ? `(${gearScore}/100 raid)` : '✓ RAID READY'}</span>
                  </span>
                  <span className={`stat-value text-[11px] ${gearScore >= 100 ? 'text-purple-400' : 'text-gray-400'}`}>
                    {gearScore}
                  </span>
                </div>
                {(player?.raids_cleared ?? 0) > 0 && (
                  <div className="stat-header mt-1">
                    <span className="stat-label text-[9px]">RAIDS</span>
                    <span className="stat-value text-purple-400 text-[11px]">★ {player.raids_cleared}</span>
                  </div>
                )}
              </div>

              <div className="stat-item">
                <div className="stat-header">
                  <span className="stat-label">XP{restedXp > 0 ? ' 💤 RESTED' : ''}</span>
                  <span className="stat-value">{player?.xp || 0} / {player?.next_level_xp || 100}</span>
                </div>
                <div className="progress-container" style={{ position: 'relative' }}>
                  {/* Rested XP pool shown as a faint teal overlay behind the XP fill */}
                  {restedXp > 0 && restedXpCap > 0 && (
                    <div style={{
                      position: 'absolute', left: 0, top: 0, height: '100%',
                      width: `${Math.min(100, (restedXp / (player?.next_level_xp || 100)) * 100)}%`,
                      background: 'rgba(0,200,200,0.25)', borderRadius: 4,
                    }} />
                  )}
                  <div className="progress-fill xp-fill" style={{ width: `${((player?.xp || 0) / (player?.next_level_xp || 100)) * 100}%` }}>
                    <div className="progress-shine" />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </header>
      )}

      <div className="main-content-wrapper game-layout">
        {/* COLUMN 1: THE CORE FEED — swaps to dungeon theater when in a run */}
        <div className="terminal-column">
          {!dungeonRun && renderWeather()}
          {dungeonRun
            ? renderDungeonTheater()
            : (
              <div className={`glass-panel terminal-wrapper flex-1${autoAttackTarget ? ' combat-pulse' : isGathering ? ' gather-pulse' : ''}`}>
                <div className="terminal-output" ref={scrollRef}>
                  {logs.map((log, i) => (
                    <div key={i} className={`terminal-line log-${log.type}`}>
                      {renderLogText(log.text)}
                    </div>
                  ))}
                </div>
              </div>
            )
          }
        </div>

        {/* COLUMN 2: NAVIGATION & STATUS */}
        <div className={`side-column ${step === 'game' ? 'unlocked-panel' : 'locked-panel'}`}>
          <div className="glass-panel actions-panel">
            <div className="actions-content scrollable scrollable-content">
              <div className="panel-header header-nav">NAVIGATION</div>
              <div style={{ height: '32px', width: '100%' }} />
              <div className="pb-12">{renderMap()}</div>

              <div className="pb-12">
                <div className="panel-header header-equipment">EQUIPMENT</div>
                <div style={{ height: '32px', width: '100%' }} />
                <div>{renderPaperdoll()}</div>
              </div>

              <div className="pb-12">
                <div>{renderPotions()}</div>
              </div>

              <div className="pb-12">
                <div className="panel-header header-bags">
                  BAGS
                  <span className={`ml-2 text-[10px] font-normal ${(player?.inventory?.length || 0) >= 16 ? 'text-red-400' : 'text-white/30'}`}>
                    {player?.inventory?.length || 0}/16
                  </span>
                </div>
                <div style={{ height: '32px', width: '100%' }} />
                <div>{renderInventory()}</div>
              </div>

              {dungeonRun && (
                <div className="pb-12">
                  <div className="panel-header header-nearby">PARTY</div>
                  <div style={{ height: '32px', width: '100%' }} />
                  <div className="space-y-2 px-1">
                    {(dungeonRun.party || []).map((m: any) => {
                      const pct = Math.max(0, Math.min(100, (m.hp / (m.max_hp || 1)) * 100));
                      const roleColor = m.role === 'healer' ? 'text-green-400' : m.role === 'tank' ? 'text-blue-400' : 'text-red-400';
                      return (
                        <div key={m.id} className={`text-xs ${!m.is_alive ? 'opacity-30' : ''}`}>
                          <div className="flex justify-between">
                            <span className="text-gray-200 font-bold">{m.name}</span>
                            <span className={`text-[10px] ${roleColor}`}>{m.role.toUpperCase()}</span>
                          </div>
                          <div className="progress-container mt-0.5" style={{ height: '5px' }}>
                            <div className="hp-fill transition-all duration-300" style={{ width: `${pct}%`, height: '100%' }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="pb-12">
                <div className="panel-header header-nearby" />
                <div style={{ height: '32px', width: '100%' }} />
                <div className="space-y-3">
                  {(() => {
                    const loc = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
                    const nowTs = Date.now() / 1000;
                    const hasQuestGiver = loc?.npcs?.some((n: any) => n.role === 'quest_giver');
                    const completedQuests = (player?.active_quests || []).filter((q: any) => q.is_completed);
                    // Travel unlocks after 2 turned-in quests from current zone
                    const zoneQuestsDone = (zone?.quests || []).filter((q: any) =>
                      player?.completed_quest_ids?.includes(q.id)
                    ).length;
                    const canTravel = zoneQuestsDone >= 2;

                    // Group alive mobs by name
                    const aliveMobs = (loc?.mobs || []).filter((m: any) => !m.respawn_at || m.respawn_at <= nowTs);
                    const deadMobs  = (loc?.mobs || []).filter((m: any) => m.respawn_at && m.respawn_at > nowTs);
                    const grouped: Record<string, any> = {};
                    aliveMobs.forEach((m: any) => {
                      if (!grouped[m.name]) grouped[m.name] = { ...m, count: 0, ids: [] };
                      grouped[m.name].count++;
                      grouped[m.name].ids.push(m.id);
                    });

                    return (
                      <>
                        {/* NPC buttons */}
                        {loc?.npcs?.map((n: any) => {
                          const hasRevealedQuests = revealedNpcs.has(n.id);
                          const availableQuests = (zone?.quests || []).filter((q: any) =>
                            !player?.active_quests?.some((aq: any) => aq.id === q.id) &&
                            !player?.completed_quest_ids?.includes(q.id)
                          );
                          const isVendor = n.role === 'vendor';
                          return (
                            <div key={n.id} className="space-y-1">
                              <div className="flex gap-2">
                                <div
                                  className={`action-item flex-1 font-bold ${isVendor ? 'text-yellow-300' : 'text-blue-400'}`}
                                  onClick={() => executeCommand(isVendor ? `shop` : `talk to ${n.name}`)}
                                  onMouseEnter={() => setHoveredItem({ name: n.name, slot: isVendor ? 'VENDOR' : 'NPC', description: n.role || "A denizen of this realm." })}
                                  onMouseLeave={() => setHoveredItem(null)}
                                >
                                  {isVendor ? '🛒 ' : (n.role === 'quest_giver' && availableQuests.length > 0 ? '! ' : '')}
                                  [{isVendor ? `shop at ${n.name.toLowerCase()}` : `talk to ${n.name.toLowerCase()}`}]
                                </div>
                              </div>
                              {/* Accept All button appears after talking to quest giver */}
                              {!isVendor && hasRevealedQuests && availableQuests.length > 0 && (
                                <div
                                  className="action-item text-green-400 font-bold ml-3"
                                  onClick={() => executeCommand('accept all')}
                                >
                                  ✓ [accept all quests]
                                </div>
                              )}
                            </div>
                          );
                        })}

                        {/* Turn-in button when at quest giver with completed quests */}
                        {hasQuestGiver && completedQuests.length > 0 && (
                          <div
                            className="action-item text-yellow-400 font-bold animate-pulse"
                            onClick={() => executeCommand('turn in')}
                          >
                            ★ [turn in {completedQuests.length} quest{completedQuests.length > 1 ? 's' : ''}]
                          </div>
                        )}

                        {/* Alive mob attack buttons */}
                        {Object.values(grouped).map((g: any) => {
                          const isNamed  = g.is_named;
                          const isElite  = g.is_elite;
                          const colorCls = isNamed ? 'text-purple-300' : isElite ? 'text-orange-400' : 'text-red-400';
                          const prefix   = isNamed ? '⚑ ' : isElite ? '★ ' : '⚔ ';
                          const isActive = autoAttackTarget === g.name.toLowerCase();
                          return (
                            <div key={g.name} className="flex gap-2">
                              <div
                                className={`action-item flex-1 font-bold ${colorCls} ${isActive ? 'animate-pulse' : ''}`}
                                onClick={() => isActive ? setAutoAttackTarget(null) : executeCommand(`attack ${g.name}`)}
                                onMouseEnter={() => setHoveredItem({
                                  name: g.name,
                                  slot: `${isNamed ? 'NAMED BOSS' : isElite ? 'ELITE' : 'HOSTILE'} — ${g.count > 1 ? `${g.count} alive` : 'alive'}`,
                                  stats: { HP: g.hp, Level: g.level },
                                  description: g.description || "Moves with predatory intent."
                                })}
                                onMouseLeave={() => setHoveredItem(null)}
                              >
                                {prefix}[{isActive ? 'stop attack' : `attack ${g.name.toLowerCase()}`}]{g.count > 1 ? ` ×${g.count}` : ''}
                              </div>
                              <div
                                className="action-item !px-2 text-accent/50 font-bold shrink-0"
                                onClick={() => executeCommand(`look ${g.name}`)}
                                title={`Inspect ${g.name}`}
                              >
                                ?
                              </div>
                            </div>
                          );
                        })}

                        {/* Dead mob respawn indicators */}
                        {deadMobs.length > 0 && (() => {
                          const soonest = Math.ceil(Math.min(...deadMobs.map((m: any) => m.respawn_at)) - nowTs);
                          return (
                            <div className="text-[9px] text-accent/20 uppercase tracking-widest pt-1">
                              {deadMobs.length} slain — respawn ~{soonest}s
                            </div>
                          );
                        })()}

                        {/* Travel button when zone is cleared */}
                        {canTravel && (
                          <div
                            className="action-item text-accent font-bold mt-4 animate-pulse"
                            onClick={() => executeCommand('travel')}
                          >
                            ➤ [travel to next zone] ({zoneQuestsDone}/2 quests done)
                          </div>
                        )}
                        {/* Dungeon — always visible, locked until level 10 */}
                        <div
                          className={`action-item font-bold ${!dungeonRun && player?.level >= 10 ? 'text-purple-400 cursor-pointer' : 'text-white/20 cursor-not-allowed'}`}
                          onClick={() => {
                            if (dungeonRun) { addLog('Already in a dungeon. Flee first.', 'hint'); return; }
                            player?.level >= 10
                              ? executeCommand('travel dungeon')
                              : addLog('⚑ Dungeon unlocks at Level 10. Keep grinding.', 'hint');
                          }}
                        >
                          ⚑ {dungeonRun ? '[inside dungeon]' : player?.level >= 10 ? '[enter dungeon]' : `[dungeon — lv.10 required]`}
                        </div>
                        {/* Raid — always visible, locked until level 20 */}
                        <div
                          className={`action-item font-bold ${!dungeonRun && player?.level >= 20 ? 'text-red-400 cursor-pointer' : 'text-white/20 cursor-not-allowed'}`}
                          onClick={() => {
                            if (dungeonRun) { addLog('Already in a dungeon. Flee first.', 'hint'); return; }
                            player?.level >= 20
                              ? executeCommand('travel raid')
                              : addLog('☠ Raid unlocks at Level 20. Clear dungeons first.', 'hint');
                          }}
                        >
                          ☠ {dungeonRun ? '[inside dungeon]' : player?.level >= 20 ? '[enter raid]' : `[raid — lv.20 required]`}
                        </div>
                      </>
                    );
                  })()}
                </div>
              </div>

              <div className="h-32" />
              <div className="mb-64 pb-24">
                <div className="panel-header header-lore" />
                <div style={{ height: '32px', width: '100%' }} />
                <div className="text-[18px] font-serif italic border-l-8 border-accent pl-8 py-6 text-white bg-black/80 leading-loose rounded-r shadow-2xl">
                  {biography || "The chronicle begins with the first step into the void..."}
                </div>
                <div style={{ height: '28px' }} />
                <div>
                  {/* Phase 1 — idle */}
                  {resetConfirm === null && (
                    <button
                      type="button"
                      className="tool-button !min-w-0 !px-2 !py-0.5 !text-red-400/40 !border-red-900/20 hover:!text-red-400 hover:!border-red-600/50"
                      onClick={() => setResetConfirm('choose')}
                      title="Delete this character or wipe all data"
                    >
                      ⚠ Reset
                    </button>
                  )}

                  {/* Phase 2 — choose what to delete */}
                  {resetConfirm === 'choose' && (
                    <div className="flex flex-col gap-1.5">
                      <span className="text-[9px] text-red-400/60 uppercase tracking-widest font-bold">What would you like to delete?</span>
                      <div className="flex gap-1 flex-wrap">
                        <button
                          type="button"
                          className="tool-button !min-w-0 !px-2 !py-0.5 !text-red-300/70 !border-red-800/40 hover:!text-red-300 hover:!border-red-600/50"
                          onClick={() => setResetConfirm('single')}
                          title={`Delete only ${player?.name}`}
                        >
                          {player?.name}
                        </button>
                        <button
                          type="button"
                          className="tool-button !min-w-0 !px-2 !py-0.5 !text-red-500/70 !border-red-700/40 hover:!text-red-500 hover:!border-red-600/60"
                          onClick={() => setResetConfirm('all')}
                          title="Wipe every character and all world data"
                        >
                          All Characters
                        </button>
                        <button type="button" className="tool-button !min-w-0 !px-2 !py-0.5" onClick={() => setResetConfirm(null)}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Phase 3a — confirm single character delete */}
                  {resetConfirm === 'single' && (
                    <div className="flex flex-col gap-1.5">
                      <span className="text-[9px] text-red-400 uppercase tracking-widest font-bold">
                        ⚠ Delete {player?.name} forever? All zones and progress will be lost.
                      </span>
                      <div className="flex gap-1">
                        <button
                          type="button"
                          className="tool-button !min-w-0 !px-2 !py-0.5 !text-red-400 !border-red-600/60 hover:!bg-red-900/30"
                          onClick={async () => {
                            const nameSnapshot = player?.name ?? 'Character';
                            setResetConfirm(null);
                            if (!playerId) return;
                            try {
                              const res = await fetch(`http://localhost:8000/player/${playerId}`, { method: 'DELETE' });
                              const data = await res.json();
                              if (data.success) {
                                setPlayer(null); setPlayerId(null); setZone(null);
                                setTarget(null); setAutoAttackTarget(null);
                                setActiveLoot(null); setBiography(''); setSavedPlayers([]);
                                setLogs([
                                  { text: 'SINGLE PLAYER AI MUD', type: 'system' },
                                  { text: `${nameSnapshot} deleted. Press Enter to continue.`, type: 'hint' },
                                ]);
                                setInput(''); setStep('intro');
                                setTimeout(() => inputRef.current?.focus(), 100);
                              } else { alert('Delete failed.'); }
                            } catch { alert('Could not reach backend.'); }
                          }}
                        >
                          Yes, Delete {player?.name}
                        </button>
                        <button type="button" className="tool-button !min-w-0 !px-2 !py-0.5" onClick={() => setResetConfirm(null)}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Phase 3b — confirm wipe all */}
                  {resetConfirm === 'all' && (
                    <div className="flex flex-col gap-1.5">
                      <span className="text-[9px] text-red-500 uppercase tracking-widest font-bold">
                        ⚠ Wipe every character and all world data? This cannot be undone.
                      </span>
                      <div className="flex gap-1">
                        <button
                          type="button"
                          className="tool-button !min-w-0 !px-2 !py-0.5 !text-red-500 !border-red-600/70 hover:!bg-red-900/40"
                          onClick={async () => {
                            setResetConfirm(null);
                            try {
                              const res = await fetch('http://localhost:8000/admin/reset', { method: 'POST' });
                              const data = await res.json();
                              if (data.success) {
                                setPlayer(null); setPlayerId(null); setZone(null);
                                setTarget(null); setAutoAttackTarget(null);
                                setGlobalChat([]); setExploredLocations(new Set());
                                setRevealedNpcs(new Set()); setActiveLoot(null);
                                setBiography(''); setSavedPlayers([]);
                                setLogs([
                                  { text: 'SINGLE PLAYER AI MUD', type: 'system' },
                                  { text: 'All data wiped. Press Enter to begin again.', type: 'hint' },
                                ]);
                                setInput(''); setStep('intro');
                                setTimeout(() => inputRef.current?.focus(), 100);
                              } else { alert('Reset failed: ' + (data.errors?.join(', ') ?? 'unknown error')); }
                            } catch { alert('Could not reach backend for reset.'); }
                          }}
                        >
                          Yes, Wipe All
                        </button>
                        <button type="button" className="tool-button !min-w-0 !px-2 !py-0.5" onClick={() => setResetConfirm(null)}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* COLUMN 3: WORLD LOGS */}
        <div className={`side-column-right ${step === 'game' ? 'unlocked-panel' : 'locked-panel'}`}>
          <div className="glass-panel quest-panel">
            <div className="panel-header header-quest">QUEST LOG</div>
            <div className="actions-content scrollable">
              <div className="text-[10px] text-accent/20 mb-4 uppercase tracking-[0.2em] font-bold">Current Objectives</div>
              {player?.active_quests?.length > 0 ? (
                player.active_quests.map((q: any) => (
                  <div key={q.id} className="mb-6 group">
                    <div className="flex justify-between items-baseline">
                      <div className={`text-[11px] font-bold transition-colors ${q.is_completed ? 'text-yellow-400' : 'text-accent/80 group-hover:text-accent'}`}>
                        {q.is_completed ? '★ ' : ''}{q.title}
                      </div>
                      <div className="text-[10px] text-accent/50">{q.current_progress}/{q.target_count}</div>
                    </div>
                    <div className="text-[9px] text-accent/40 mt-1">{q.objective}</div>
                    <div className="w-full bg-black/40 h-[2px] mt-2 rounded-full overflow-hidden">
                      <div
                        className={`h-full transition-all duration-1000 ${q.is_completed ? 'bg-yellow-400' : 'bg-accent'}`}
                        style={{ width: `${Math.min(100, (q.current_progress / q.target_count) * 100)}%` }}
                      />
                    </div>
                    {q.is_completed && (
                      <div
                        className="text-[9px] text-yellow-400/80 mt-1 cursor-pointer hover:text-yellow-300 uppercase tracking-widest"
                        onClick={() => executeCommand('turn in')}
                      >
                        → Return to quest giver
                      </div>
                    )}
                  </div>
                ))
              ) : (
                <div className="text-[10px] opacity-20 italic">Seek a quest giver to begin your chronicles.</div>
              )}
            </div>
          </div>

          <div className="glass-panel chat-panel">
            <div className="panel-header header-chat">
              <span>WORLD CHAT</span>
            </div>
            <div className="flex-1 overflow-y-auto p-4 font-mono text-sm chat-content scrollable" ref={chatScrollRef}>
              <div className="mt-auto">
                {globalChat.map((msg, i) => {
                  const isMe = msg.name === player?.name;
                  const isWorld = msg.name === "World";
                  return (
                    <div key={i} className={`message-wrapper ${isMe ? 'text-right' : ''}`}>
                      {isWorld ? (
                        <span className="chat-world">✦ {msg.text}</span>
                      ) : (
                        <>
                          <span className={isMe ? 'chat-name-me' : 'chat-name-other'}>[{msg.name}]: </span>
                          <span>{msg.text}</span>
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
            {/* World Chat Input Area */}
            <div className="chat-input-area">
              <form onSubmit={handleWorldChat} className="flex gap-2 w-full">
                <input
                  type="text"
                  value={worldInput}
                  onChange={(e) => setWorldInput(e.target.value)}
                  placeholder="Simulated friends online..."
                  className="" /* Styles handled in globals.css */
                />
                <button
                  type="submit"
                  className="" /* Styles handled in globals.css */
                >
                  Send
                </button>
              </form>
            </div>
          </div>
        </div>
      </div>

      {/* GLOBAL ACTION BAR */}
      {step === 'game' && (
        <div className="quick-toolbar">
          <button type="button" className="tool-button relative !bg-accent/5" onClick={() => executeCommand('look')}>
            Look
            <span className="keybind-hint">1</span>
          </button>

          {(() => {
            let currentIdx = 2;
            const loc = zone?.locations?.find((l: any) => l.id === player?.current_location_id);
            const exits = loc?.exits || {};
            const nowTs = Date.now() / 1000;

            // Unique alive mob names sorted: regular → elite → named
            const aliveMobs = (loc?.mobs || []).filter((m: any) => !m.respawn_at || m.respawn_at <= nowTs);
            const mobRank = (name: string) => {
              const ms = aliveMobs.filter((m: any) => m.name === name);
              return ms.some((m: any) => m.is_named) ? 2 : ms.some((m: any) => m.is_elite) ? 1 : 0;
            };
            const aliveMobNames = ([...new Set(aliveMobs.map((m: any) => m.name))] as string[])
              .sort((a, b) => mobRank(a) - mobRank(b));

            const completedQuests = (player?.active_quests || []).filter((q: any) => q.is_completed);
            const hasQuestGiver = loc?.npcs?.some((n: any) => n.role === 'quest_giver');

            return (
              <>
                {/* Direction buttons */}
                {Object.entries(exits).map(([dir, id]) => {
                  const btn = (
                    <button key={id as string} type="button" className="tool-button relative !text-green-500/60" onClick={() => executeCommand(`go ${dir}`)}>
                      {dir.toUpperCase()}
                      <span className="keybind-hint">{currentIdx}</span>
                    </button>
                  );
                  currentIdx++;
                  return btn;
                })}

                {/* Dynamic attack buttons — one per unique alive mob type */}
                {aliveMobNames.map(name => {
                  const mobsOfType = (loc?.mobs || []).filter((m: any) =>
                    m.name === name && (!m.respawn_at || m.respawn_at <= nowTs)
                  );
                  const count    = mobsOfType.length;
                  const isElite  = mobsOfType.some((m: any) => m.is_elite);
                  const isNamed  = mobsOfType.some((m: any) => m.is_named);
                  const isActive = autoAttackTarget === name.toLowerCase();
                  const label    = isNamed ? `⚑ ${name}` : isElite ? `★ ${name}` : name;
                  const colorCls = isNamed
                    ? '!text-purple-300/90 !border-purple-900/60'
                    : isElite
                    ? '!text-orange-400/90 !border-orange-900/50'
                    : '!text-red-400/80 !border-red-900/40';
                  const btn = (
                    <button
                      key={`atk-${name}`}
                      type="button"
                      className={`tool-button relative overflow-hidden ${colorCls} ${isActive ? 'ring-1 ring-red-500/40' : ''}`}
                      onClick={() => isActive ? setAutoAttackTarget(null) : executeCommand(`attack ${name}`)}
                      title={isActive ? `Auto-attacking ${name} — click to stop` : `Attack ${name}`}
                    >
                      {/* Cooldown drain overlay */}
                      {isActive && (
                        <div
                          className="absolute inset-0 bg-red-900/30 origin-left transition-none"
                          style={{ transform: `scaleX(${attackCooldown / 100})` }}
                        />
                      )}
                      <span className="relative z-10">⚔ {label}{count > 1 ? ` ×${count}` : ''}{isActive ? ' ■' : ''}</span>
                      <span className="keybind-hint">{currentIdx}</span>
                    </button>
                  );
                  currentIdx++;
                  return btn;
                })}

                {/* Flee button during auto-attack */}
                {autoAttackTarget && (
                  <button
                    type="button"
                    className="tool-button relative !text-orange-400/80 !border-orange-900/40"
                    onClick={() => executeCommand('flee')}
                    title="Flee from combat"
                  >
                    ↩ Flee
                  </button>
                )}

                {/* Turn-in button (pulsing yellow when quests ready) */}
                {hasQuestGiver && completedQuests.length > 0 && (
                  <button
                    type="button"
                    className="tool-button relative !text-yellow-400/90 !border-yellow-900/40 animate-pulse"
                    onClick={() => executeCommand('turn in')}
                    title="Turn in completed quests"
                  >
                    ★ Turn In
                    <span className="keybind-hint">{currentIdx++}</span>
                  </button>
                )}

                {/* Dynamic Talk buttons — one per quest-giver NPC at current location */}
                {(loc?.npcs || []).filter((n: any) => n.role === 'quest_giver').map((n: any) => (
                  <button key={n.id} type="button" className="tool-button relative !text-blue-400/80" onClick={() => executeCommand(`talk to ${n.name}`)}>
                    Talk
                    <span className="keybind-hint">{currentIdx++}</span>
                  </button>
                ))}

                {/* Shop + Sell buttons — one per vendor NPC at current location */}
                {(loc?.npcs || []).filter((n: any) => n.role === 'vendor').flatMap((n: any) => {
                  const btns = [
                    <button key={`${n.id}-shop`} type="button" className="tool-button relative !text-yellow-500/80" onClick={() => executeCommand('shop')}>
                      Shop
                      <span className="keybind-hint">{currentIdx++}</span>
                    </button>
                  ];
                  if ((player?.inventory || []).length > 0) {
                    btns.push(
                      <button key={`${n.id}-sell`} type="button" className="tool-button relative !text-yellow-500/50" onClick={() => executeCommand('sell')}>
                        Sell
                        <span className="keybind-hint">{currentIdx++}</span>
                      </button>
                    );
                  }
                  return btns;
                })}

                {/* GATHER — only shown when a forage quest targets this location */}
                {(player?.active_quests || []).some((q: any) =>
                  q.quest_type === 'forage' &&
                  q.target_id === player?.current_location_id &&
                  !q.is_completed
                ) && (
                  <button
                    type="button"
                    className={`tool-button relative overflow-hidden !text-green-400/90 !border-green-900/50 ${isGathering ? 'opacity-50 cursor-not-allowed animate-pulse' : ''}`}
                    disabled={isGathering}
                    onClick={() => executeCommand('gather')}
                    title="Forage for resources"
                  >
                    {(isGathering || gatherCooldown > 0) && (
                      <span
                        className="absolute inset-0 origin-left bg-green-900/40 transition-none"
                        style={{ transform: `scaleX(${gatherCooldown > 0 ? gatherCooldown / 100 : 1})` }}
                      />
                    )}
                    <span className="relative">{isGathering ? 'Gathering...' : 'Gather'}</span>
                    <span className="keybind-hint">{currentIdx++}</span>
                  </button>
                )}

                <button type="button" className="tool-button relative" onClick={() => executeCommand('quests')}>
                  Quests
                  <span className="keybind-hint">{currentIdx++}</span>
                </button>
                <button type="button" className="tool-button relative" onClick={() => executeCommand('inventory')}>
                  Bags
                  <span className="keybind-hint">{currentIdx++}</span>
                </button>
                <button type="button" className="tool-button relative" onClick={() => executeCommand('who')}>
                  Who
                  <span className="keybind-hint">{currentIdx++}</span>
                </button>
                <button type="button" className="tool-button relative !text-accent/30" onClick={() => executeCommand('help')}>
                  Help
                  <span className="keybind-hint">?</span>
                </button>
              </>
            );
          })()}
        </div>
      )}

      <div className="input-area-wrapper relative flex-shrink-0">
        {isTalking && (
          <div className="absolute -top-12 left-4 px-4 py-1.5 bg-black/90 border border-accent/20 rounded text-[10px] text-accent font-black uppercase tracking-[0.3em] animate-pulse">
            Receiving Transmission...
          </div>
        )}
        <form onSubmit={handleCommand} className="input-area">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              step === 'intro' ? "ACCESS THE CHRONICLES..." :
                step === 'load' ? "TYPE NUMBER TO LOAD OR 'NEW'..." :
                  step === 'race' ? "SELECT YOUR LINEAGE..." :
                    step === 'class' ? "SELECT YOUR CALLING..." :
                      "TYPE COMMAND..."
            }
            ref={inputRef}
            className="mud-input font-mono !pl-8"
            autoFocus
          />
        </form>
      </div>
      {renderTooltip()}
    </main>
  );
}
