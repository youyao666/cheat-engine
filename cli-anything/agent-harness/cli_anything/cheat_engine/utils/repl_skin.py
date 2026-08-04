from __future__ import annotations


class ReplSkin:
    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version

    def print_banner(self) -> None:
        print(f"{self.name} {self.version} - Cheat Engine agent REPL")
        print("Type 'help' for commands or 'exit' to close the REPL.")

    def create_prompt_session(self):
        try:
            from prompt_toolkit import PromptSession

            return PromptSession(history=None)
        except ImportError:
            return None

    def get_input(self, session) -> str:
        if session is None:
            return input("ce-ai> ")
        return session.prompt("ce-ai> ")

    def print_goodbye(self) -> None:
        print("Cheat Engine agent REPL closed.")
