#!/usr/bin/env python3
import pexpect
import sys
import os

def run_test():
    env = os.environ.copy()
    env["DRY_RUN"] = "1"
    
    print("Starting interactive CLI test...")
    # Spawn the process
    child = pexpect.spawn('python main.py', env=env, encoding='utf-8', timeout=5, dimensions=(100, 200))
    
    try:
        # 1. Wait for Main Menu
        child.expect("원하는 작업을 선택하세요", timeout=5)
        print("[1/8] Main menu loaded. Selecting 'start'...")
        child.send('\r') # Enter
        
        # 2. Wait for Workspace Selection
        child.expect("미션을 수행할 작업 디렉토리를 선택하세요", timeout=5)
        print("[2/8] Workspace menu loaded. Selecting '__new__'...")
        import time
        for _ in range(2):
            child.send('\033[B') 
            time.sleep(0.1)
        child.send('\r') 
        
        # 3. Enter new path with Tab expansion
        child.expect("새로운 작업 디렉토리 경로를 입력하세요", timeout=5)
        print("[3/8] Workspace prompt loaded. Typing '~/' and TAB...")
        child.send('~/\t\r') # Type ~/ then Tab then Enter
        
        # 4. Wait for Mission Prompt
        child.expect("새로운 미션을 입력하세요", timeout=5)
        print("[4/8] Mission prompt loaded. Typing mission and double ENTER...")
        child.send('E2E Headless Verification Test\n\n')
        
        # 5. Persona Selection loop
        child.expect("현재 추가된 에이전트: 0명", timeout=5)
        print("[5/8] Persona menu loaded. Selecting default persona (engineer)...")
        # Select first persona (architect) or second (engineer) etc. We just hit Enter to pick the first one.
        child.send('\r')
        
        # 6. Engine Selection
        child.expect("어떤 모델 엔진을 사용할까요", timeout=5)
        print("[6/8] Engine menu loaded. Selecting default...")
        child.send('\r')
        
        # 7. Count Selection
        child.expect("몇 명을 투입할까요", timeout=5)
        print("[7/8] Count menu loaded. Selecting 1...")
        child.send('\r')
        
        # 8. Persona loop complete
        child.expect("현재 추가된 에이전트: 1명", timeout=5)
        print("[8/8] Finishing persona selection...")
        # Move up to `__done__` (it's the last item)
        child.send('\033[A\r')
        
        # 9. Execution Mode
        child.expect("실행 모드 선택", timeout=5)
        print("[9/9] Execution mode menu loaded. Selecting default...")
        child.send('\r')
        
        # 10. Check for success
        child.expect("DRY_RUN mode enabled", timeout=5)
        child.expect("미션이 완료되었습니다", timeout=5)
        
        # 11. Follow-up
        child.expect("다음 작업을 선택하세요", timeout=5)
        print("\n✅ All interactive UI features verified successfully! Exiting follow-up...")
        # send down arrow and enter to exit to main menu
        child.send('\033[B\r')
        
        # Quit the app safely
        child.expect("원하는 작업을 선택하세요", timeout=5)
        # Choose quit (third option)
        child.send('\033[B\033[B\r') 
        child.expect(pexpect.EOF)
        
    except pexpect.TIMEOUT as e:
        print("\n❌ Test failed due to timeout.")
        print(f"Before: {child.before}")
        sys.exit(1)
    except pexpect.EOF as e:
        print("\n❌ Test failed due to unexpected EOF.")
        print(f"Before: {child.before}")
        sys.exit(1)

if __name__ == "__main__":
    run_test()