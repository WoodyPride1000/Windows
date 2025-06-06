
# Hyper-V をハイパーバイザー型（Type-1）として再構築する手順（Windows PC 向け）

---

## ✅ ステップ 0：BIOS/UEFI で仮想化支援機能を有効にする

1. PC を再起動し、BIOS または UEFI の設定画面に入る（通常は起動時に `Del`, `F2`, `F10`, `Esc` のいずれかを押す）。
2. 以下の設定が「**Enabled（有効）」になっていることを確認する：
   - **Intel CPU** の場合: `Intel Virtualization Technology (VT-x)`、`VT-d`
   - **AMD CPU** の場合: `AMD-V`、`SVM`、`IOMMU`
3. 設定を保存して終了し、Windows を起動。

---

## 🧹 ステップ 1：Hyper-V を完全にアンインストールする

管理者権限の **コマンドプロンプト** で以下を実行：

```bash
DISM /Online /Disable-Feature /FeatureName:Microsoft-Hyper-V-All
```

または GUI で：
- 「Windows の機能の有効化または無効化」を開く
- `Hyper-V` 関連のチェックをすべて外す

---

## 🔄 ステップ 2：再起動する

PC を再起動して、Hyper-V の無効化を反映させる。

---

## 🧱 ステップ 3：Hyper-V を再インストール（Type-1 ハイパーバイザーとして）

管理者権限の **コマンドプロンプト** または **PowerShell** で以下を実行：

```bash
DISM /Online /Enable-Feature /All /FeatureName:Microsoft-Hyper-V-All
```

PowerShell の場合：

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All
```

---

## 🔄 ステップ 4：再起動する

再度 PC を再起動して、Hyper-V の有効化を反映させる。

---

## 🔍 ステップ 5：Hyper-V が Type-1 ハイパーバイザーとして動作しているか確認

管理者権限の PowerShell で以下を実行：

```powershell
Get-WmiObject Win32_ComputerSystem | Select-Object HypervisorPresent
```

または：

```powershell
systeminfo | findstr /i "Hyper-V"
```

- `HypervisorPresent : True` または  
- `A hypervisor has been detected` が表示されれば成功。

---

## 💡 補足：追加の確認ポイント（必要に応じて）

- **仮想スイッチが正しく構成されているか**
  - Hyper-V マネージャー → 仮想スイッチ マネージャーで確認・再作成可能
- **他のハイパーバイザー（VirtualBox / VMware）との競合回避**
  - これらは Hyper-V 有効時に正常に動作しないことがある
- **WSL2 / Docker を併用する場合の設定確認**

---
