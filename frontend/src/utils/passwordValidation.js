export function validateNewPasswordWithConfirmation(newPassword, confirmPassword) {
  if (!newPassword) {
    return '新密码不能为空'
  }
  if (newPassword.length < 6) {
    return '新密码至少 6 位'
  }
  if (newPassword !== confirmPassword) {
    return '两次输入的密码不一致'
  }
  return ''
}
