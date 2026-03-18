import asyncio
import random
import time
from typing import List, Dict, Any
from app.models.schemas import Zone, SimulatedPlayer
from app.core.vector_db import vec_db
from app.core.scaling_math import ScalingMath
import math

class SimulationEngine:
    def __init__(self):
        self.active_zones: Dict[str, float] = {} # zone_id -> last_tick_time
        self.player_zones: set[str] = set()       # zone_ids with a real player present
        self.running = False

    def mark_player_zone(self, zone_id: str):
        """Track only the current zone — replace old entry so stale zones stop generating ambiance."""
        self.player_zones = {zone_id}

    async def start(self):
        if self.running: return
        self.running = True
        asyncio.create_task(self._simulation_loop())

    async def _simulation_loop(self):
        while self.running:
            # Logic to find "active" zones (e.g. zones with real players)
            # For simplicity in this MUD, we just simulate whatever is in the cache or known
            zone_ids = list(vec_db._zone_cache.keys())
            
            for zone_id in zone_ids:
                await self.simulate_zone(zone_id)
                # Progress time of day (1 full cycle ~12 mins at 10s ticks)
                z_data = await vec_db.get_zone(zone_id)
                if z_data:
                    z_data['time_of_day'] = (z_data.get('time_of_day', 0.5) + 0.01) % 1.0
                    
                    # 5% chance to shift weather — constrained by time of day
                    if random.random() < 0.05:
                        tod = z_data.get('time_of_day', 0.5)
                        # Night (0.0–0.25 and 0.85–1.0): no sunny — use night-appropriate options
                        if tod < 0.25 or tod > 0.85:
                            z_data['weather'] = random.choice(["foggy", "clear", "stormy", "stormy", "foggy"])
                        # Dawn/dusk (0.25–0.35 and 0.75–0.85): transitional
                        elif tod < 0.35 or tod > 0.75:
                            z_data['weather'] = random.choice(["foggy", "cloudy", "rainy", "clear"])
                        # Day (0.35–0.75): full palette including sunny
                        else:
                            z_data['weather'] = random.choice(["sunny", "sunny", "sunny", "cloudy", "rainy", "foggy", "stormy"])
                    
                    await vec_db.save_zone(zone_id, z_data)

                # 10% chance to generate world ambiance — only for zones with a real player
                if zone_id in self.player_zones and random.random() < 0.1:
                    await self.generate_zone_ambiance(zone_id)
            
            await asyncio.sleep(10) # Simulation tick every 10s

    async def simulate_zone(self, zone_id: str):
        z_data = await vec_db.get_zone(zone_id)
        if not z_data: return

        zone = Zone(**z_data)
        updated = False
        now = time.time()

        # Respawn dead mobs whose timer has expired.
        # Also regen alive mobs that took partial damage when no player is present —
        # prevents mobs from staying at low HP indefinitely between player visits.
        player_present = zone_id in self.player_zones
        for loc in zone.locations:
            for mob in loc.mobs:
                if mob.respawn_at is not None and now >= mob.respawn_at:
                    mob.hp = mob.max_hp
                    mob.respawn_at = None
                    updated = True
                elif not player_present and mob.respawn_at is None and mob.hp < mob.max_hp:
                    mob.hp = mob.max_hp
                    updated = True

        for sim_p in zone.simulated_players:
            # 20% chance to move or change status
            if random.random() < 0.2:
                updated = True
                action = random.choice(["exploring", "resting", "battling"])
                sim_p.status = action

                if action == "exploring" and zone.locations:
                    # Move to adjacent location
                    curr_loc = next((l for l in zone.locations if l.id == sim_p.current_location_id), zone.locations[0])
                    if curr_loc.exits:
                        target_id = random.choice(list(curr_loc.exits.values()))
                        sim_p.current_location_id = target_id

                elif action == "battling" and zone.locations:
                    # Find an alive mob at sim player's location and kill it
                    sim_loc = next((l for l in zone.locations if l.id == sim_p.current_location_id), None)
                    if sim_loc:
                        alive_mobs = [m for m in sim_loc.mobs if m.respawn_at is None and m.hp > 0]
                        if alive_mobs:
                            target = random.choice(alive_mobs)
                            target.hp = 0
                            target.respawn_at = now + 60.0
                            zone.world_messages.append(
                                f"{sim_p.name} defeats {target.name} near {sim_loc.name}."
                            )
                            zone.world_messages = zone.world_messages[-5:]

        if updated:
            await vec_db.save_zone(zone_id, zone.model_dump(mode='json'))

    async def generate_zone_ambiance(self, zone_id: str):
        z_data = await vec_db.get_zone(zone_id)
        if not z_data: return
        zone = Zone(**z_data)

        from app.core.ai_client import ai_client

        # Build grounded context — filter out collectible items masquerading as mob names
        _collectible_words = {"tusk","fang","pelt","wing","tail","hide","scale","stinger","ear","bone","claw","horn","core","essence","shard","crystal","trophy","finger","badge"}
        mob_names = list({
            m.name for loc in zone.locations for m in loc.mobs
            if m.respawn_at is None and not any(w in m.name.lower().split() for w in _collectible_words)
        })
        mob_ctx = ", ".join(mob_names[:3]) if mob_names else None
        weather = z_data.get('weather', 'clear')
        tod = z_data.get('time_of_day', 0.5)
        time_str = "night" if (tod < 0.25 or tod > 0.85) else "dawn" if tod < 0.35 else "dusk" if tod > 0.75 else "day"

        ctx_parts = [f"Zone: {zone.name}", f"Weather: {weather}", f"Time: {time_str}"]
        if mob_ctx:
            ctx_parts.append(f"Active creatures: {mob_ctx}")
        context = ". ".join(ctx_parts)

        first_mob = mob_names[0] if mob_names else "something"
        prompt = (
            f"{context}.\n"
            f"Write ONE MUD server notification, 8-12 words. "
            f"It must mention a specific creature or weather detail from the context above. "
            f"Style examples (vary the pattern): "
            f"'A {first_mob} darts through the undergrowth to the north.' "
            f"'The {weather} weather worsens — watch your footing.' "
            f"'You hear {first_mob}s moving nearby.' "
            f"'A pack of {first_mob}s emerges from the treeline.' "
            f"Output only the notification. No poetry, no metaphors, no asterisks."
        )
        system_prompt = "You are a MUD game server. Output only the notification text, no quotes."

        try:
            ambiance = await ai_client.generate_content(prompt, system_prompt, max_tokens=40)
            if ambiance and "Error" not in ambiance:
                cleaned = ambiance.strip().strip('"\'')
                # Only save if not a near-duplicate of recent messages
                if cleaned not in zone.world_messages[-3:]:
                    zone.world_messages.append(cleaned)
                    zone.world_messages = zone.world_messages[-5:]
                    await vec_db.save_zone(zone_id, zone.model_dump(mode='json'))
                    print(f"DEBUG: Ambiance generated for {zone.name}: {cleaned}")
        except Exception as e:
            print(f"DEBUG: Ambiance generation failed: {e}")

sim_engine = SimulationEngine()
