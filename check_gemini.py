"""Quick Gemini check: python check_gemini.py"""
import os, time
import app
t = time.time()
reply, tokens = app.ask_llm("check", "Say hello in isiXhosa.", "xh")
print(f"{time.time()-t:.1f}s | tokens={tokens} | {reply}")
print("OK" if tokens else "FAIL: see error above (check GEMINI_API_KEY / LLM_MODEL / internet)")
