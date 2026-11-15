;;; emacs-mozc-init.el -- mozc 入力の検証用最小 init
;;
;; usage:
;;   emacs -Q -l tools/emacs-mozc-init.el /tmp/test.txt &
;;
;; この init は 2 つの経路を切り替えられる:
;;
;; [A] mozc.el 直接接続 (既定。emacs-mozc パッケージが必要)
;;     emacs -> mozc_emacs_helper -> mozc_server
;;     fcitx5 を介さない。emacs の input-method として動作し、
;;     preedit/候補は emacs 内に描画される。C-\ (toggle-input-method) で開始。
;;
;; [B] XIM 経由 (fcitx5 経由。起動時の環境変数で選択)
;;     XMODIFIERS=@im=fcitx GTK_IM_MODULE=fcitx emacs ...
;;     C-Space (fcitx5 トリガー) で mozc 活性化。
;;     emacs -Q で何も設定しなくても XIM 接続されれば使える。
;;
;; シェル側の設定 (XIM 経路を常用する場合。~/.profile に書く):
;;   export XMODIFIERS=@im=fcitx
;;   export GTK_IM_MODULE=fcitx
;;   # fcitx5 側は起動済みであること: fcitx5 -d --disable=wayland
;;
;; mozc.el を常用する場合の ~/.emacs.d 側の設定例 (rebirth/lisp などに):
;;   (add-to-list 'load-path "/usr/share/emacs/site-lisp/mozc")
;;   (require 'mozc)
;;   (setq default-input-method "japanese-mozc")
;;   ;; 任意: 候補をミニバッファではなく overlay で出す
;;   ;; (setq mozc-candidate-style 'overlay)

;; --- [A] mozc.el ---
;; emacs-mozc パッケージは apt 版 emacs を依存で引き込むため使わず、
;; emacs-mozc-bin (helper のみ) + deb から取り出した mozc.el の組み合わせ:
;;   sudo apt install emacs-mozc-bin
;;   cd /tmp && apt download emacs-mozc && dpkg -x emacs-mozc_*_all.deb emacs-mozc-x
;;   mkdir -p ~/.local/share/emacs/site-lisp
;;   cp -r /tmp/emacs-mozc-x/usr/share/emacs/site-lisp/mozc ~/.local/share/emacs/site-lisp/
(dolist (dir '("~/.local/share/emacs/site-lisp/mozc"
               "/usr/share/emacs/site-lisp/mozc"))
  (when (file-directory-p dir)
    (add-to-list 'load-path dir)))
(when (locate-library "mozc")
  (require 'mozc)
  (setq default-input-method "japanese-mozc"))

;; 検証用: emacsclient からバッファ内容を読めるように server を立てる
(require 'server)
(unless (server-running-p) (server-start))

;;; emacs-mozc-init.el ends here
