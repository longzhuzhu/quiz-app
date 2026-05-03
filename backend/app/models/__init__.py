"""模型导出 - 统一导入路径"""

from app.models.user import User
from app.models.question_bank import QuestionBank
from app.models.question import Question
from app.models.quiz import QuizSession, QuizAnswer
from app.models.wrong import WrongAnswer, UserQuestionStat
from app.models.vocabulary import Vocabulary, UserVocabProgress
from app.models.bank_word import BankWordFrequency, UserBankWordProgress, BankWordExclusion
from app.models.background_job import BackgroundJob
from app.models.system_setting import SystemSetting

__all__ = [
    "User",
    "QuestionBank",
    "Question",
    "QuizSession",
    "QuizAnswer",
    "WrongAnswer",
    "UserQuestionStat",
    "Vocabulary",
    "UserVocabProgress",
    "BankWordFrequency",
    "UserBankWordProgress",
    "BankWordExclusion",
    "BackgroundJob",
    "SystemSetting",
]
