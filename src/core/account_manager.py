"""Менеджер активных аккаунтов (до 3-х)."""

from src.core.user import User


class AccountManager:
    def __init__(self):
        self.accounts: list[User] = []
        self.current_index: int = -1

    def add_account(self, user: User) -> bool:
        for acc in self.accounts:
            if acc.fp16 == user.fp16:
                self.current_index = self.accounts.index(acc)
                return False

        if len(self.accounts) >= 3:
            raise ValueError("Максимум 3 аккаунта")

        self.accounts.append(user)
        self.current_index = len(self.accounts) - 1
        return True

    def remove_account(self, fp16: str):
        from src.core.user import logout_user

        for i, acc in enumerate(self.accounts):
            if acc.fp16 == fp16:
                logout_user(acc)
                self.accounts.pop(i)

                if self.current_index >= len(self.accounts):
                    self.current_index = len(self.accounts) - 1
                return

    def get_current(self) -> User | None:
        if 0 <= self.current_index < len(self.accounts):
            return self.accounts[self.current_index]
        return None

    def switch_to(self, fp16: str):
        for i, acc in enumerate(self.accounts):
            if acc.fp16 == fp16:
                self.current_index = i
                return