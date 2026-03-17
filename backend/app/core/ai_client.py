import openai
import os
from typing import List, Dict, Any
import json

# Set LM_STUDIO_MODEL env var to match your loaded model name, e.g.:
#   export LM_STUDIO_MODEL="llama-3.2-3b-instruct"
# LM Studio also accepts any string and routes to the currently loaded model.
_MODEL = os.environ.get("LM_STUDIO_MODEL", "local-model")

class LMStudioClient:
    def __init__(self, base_url: str = "http://localhost:1234/v1"):
        self.client = openai.AsyncOpenAI(base_url=base_url, api_key="lm-studio")

    async def generate_content(self, prompt: str, system_prompt: str = "You are a direct game engine. Output ONLY the text intended for the player. NEVER include thought blocks, reasoning, <thought> tags, or 'Thinking Process'. If you think, do it silently and do not output it.", max_tokens: int = 150) -> str:
        print(f"DEBUG: Generating content with prompt: {prompt[:50]}...")
        try:
            response = await self.client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=max_tokens,
                timeout=20.0
            )
            print("DEBUG: Content generated successfully.")
            return response.choices[0].message.content
        except Exception as e:
            print(f"DEBUG: AI Generation failed: {e}")
            raise e

    async def stream_content(self, prompt: str, system_prompt: str = "You are a direct game engine. Output ONLY the narrative storyline. NEVER output reasoning, thoughts, or metadata. Stay in character but keep output strictly for the player.", max_tokens: int = 150):
        print(f"DEBUG: Streaming content with prompt: {prompt[:50]}...")
        try:
            stream = await self.client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=max_tokens,
                stream=True,
                timeout=15.0
            )
            
            # Robust Thought-stripping state
            in_thought_block = False
            buffer = ""
            keywords = ["Thinking Process:", "<thought>", "thought>", "Thinking:", "Thought:", "Reasoning:"] # Expanded markers
            
            async for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    buffer += content
                    
                    if not in_thought_block:
                        # Check if we're entering a thought block
                        if any(k in buffer for k in keywords):
                            in_thought_block = True
                            # Keep what was before the keyword
                            for k in keywords:
                                if k in buffer:
                                    # Output everything before the thought block start
                                    pre_thought = buffer.split(k)[0]
                                    if pre_thought:
                                        yield pre_thought
                                    buffer = "" # Clear buffer, start skipping
                                    break
                            continue
                        
                        # If no keyword found and buffer grows, output it
                        if len(buffer) > 20: # Keep small buffer to catch split keywords
                            yield buffer[:-20]
                            buffer = buffer[-20:]
                    else:
                        # We are skipping thought content
                        if "</thought>" in buffer or "\n\n" in buffer:
                            in_thought_block = False
                            # Find the break point
                            if "</thought>" in buffer:
                                buffer = buffer.split("</thought>")[-1]
                            else:
                                buffer = "" # Assuming double newline meant end of thinking
                            continue
                        
                        # Limit buffer growth while skipping
                        if len(buffer) > 500:
                            buffer = buffer[-200:]
            
            # Final yield
            if not in_thought_block and buffer:
                yield buffer
                
        except Exception as e:
            print(f"DEBUG: AI Streaming failed: {e}")
            raise e

    async def generate_json(self, prompt: str, system_prompt: str, max_tokens: int = 700) -> Dict:
        print(f"DEBUG: Starting AI JSON generation for prompt: {prompt[:50]}...")
        raw_text = await self.generate_content(prompt, system_prompt, max_tokens=max_tokens)
        try:
            # Clean possible markdown formatting
            cleaned = raw_text.strip().replace('```json', '').replace('```', '').strip()
            result = json.loads(cleaned)
            print("DEBUG: AI JSON generation successful.")
            return result
        except Exception as e:
            print(f"DEBUG: Failed to parse AI JSON: {e}")
            raise e


ai_client = LMStudioClient()
