import 'package:flutter/material.dart';

import '../api.dart';
import '../scope.dart';
import '../services.dart';
import '../theme.dart';
import '../ui.dart';
import '../widgets.dart';

final _emailRe = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');

String? _emailError(String v) => _emailRe.hasMatch(v.trim()) ? null : "That doesn't look like an email address.";

/// 84px yellow rounded square with an icon, used on the "check your email" screens.
class CxIconTile extends StatelessWidget {
  const CxIconTile(this.icon, {super.key});
  final IconData icon;
  @override
  Widget build(BuildContext context) => Align(
        alignment: Alignment.centerLeft,
        child: ExcludeSemantics(
          child: Container(
            width: 84,
            height: 84,
            decoration: BoxDecoration(color: Cx.accent, borderRadius: BorderRadius.circular(26)),
            child: Icon(icon, size: 40, color: Cx.ground),
          ),
        ),
      );
}

/// Yellow text link, 44px tall, centred or left.
class CxYellowLink extends StatelessWidget {
  const CxYellowLink(this.label, {super.key, required this.onTap, this.center = true});
  final String label;
  final VoidCallback onTap;
  final bool center;
  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        label: label,
        excludeSemantics: true,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: onTap,
          child: Container(
            constraints: const BoxConstraints(minHeight: 44),
            alignment: center ? Alignment.center : Alignment.centerLeft,
            padding: EdgeInsets.only(left: center ? 0 : 8),
            child: Text(label, style: const TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 15, fontWeight: FontWeight.w600, color: Cx.accent)),
          ),
        ),
      );
}

class SignInScreen extends StatefulWidget {
  const SignInScreen({super.key, this.notice});
  final String? notice;
  @override
  State<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends State<SignInScreen> {
  final email = TextEditingController();
  final pw = TextEditingController();
  String? emailErr, formErr;
  bool busy = false;
  bool unverified = false;

  Future<void> _submit() async {
    setState(() {
      emailErr = _emailError(email.text);
      formErr = null;
      unverified = false;
    });
    if (emailErr != null) return;
    if (pw.text.isEmpty) {
      setState(() => formErr = 'Enter your password.');
      return;
    }
    setState(() => busy = true);
    final session = SessionScope.of(context);
    final nav = Navigator.of(context);
    try {
      await session.signIn(email.text, pw.text);
      nav.popUntil((r) => r.isFirst);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        formErr = e.message;
        unverified = e.unverified;
        busy = false;
      });
    } on Exception {
      if (!mounted) return;
      setState(() {
        formErr = 'Something went wrong. Try again.';
        busy = false;
      });
    }
  }

  @override
  void dispose() {
    email.dispose();
    pw.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => CxScreen(children: [
        const CxTop(back: false, logo: true, title: 'Asirive Cortex'),
        const CxSpace(44),
        const CxTitle('Sign\nin', size: 64, height: .95),
        const CxText('Manage your glasses and the people who look after you.'),
        if (widget.notice != null) CxText(widget.notice!, color: Cx.text),
        CxField(label: 'Email', controller: email, keyboard: TextInputType.emailAddress, autofill: const [AutofillHints.email], error: emailErr),
        CxField(label: 'Password', controller: pw, obscure: true, autofill: const [AutofillHints.password], onSubmit: _submit, error: formErr),
        if (unverified)
          CxYellowLink('Send the confirmation email again', center: false, onTap: () async {
            try {
              await SessionScope.of(context).api.resend(email.text.trim());
              if (!mounted) return;
              setState(() => formErr = 'Sent. Check your email.');
            } on ApiException catch (e) {
              if (!mounted) return;
              setState(() => formErr = e.message);
            }
          }),
        CxYellowLink('Forgot your password?', center: false, onTap: () => push(context, ForgotScreen(email: email.text))),
      ], bottom: [
        CxButton('Sign in', onTap: _submit, busy: busy),
        CxButton('Create an account', outline: true, onTap: () => push(context, const CreateAccountScreen())),
      ]);
}

class CreateAccountScreen extends StatefulWidget {
  const CreateAccountScreen({super.key});
  @override
  State<CreateAccountScreen> createState() => _CreateAccountScreenState();
}

class _CreateAccountScreenState extends State<CreateAccountScreen> {
  final email = TextEditingController();
  final pw = TextEditingController();
  String? emailErr, pwErr, formErr;
  bool busy = false;
  bool agreed = false;

  Future<void> _submit() async {
    setState(() {
      emailErr = _emailError(email.text);
      pwErr = pw.text.length < 10 ? 'Use at least 10 characters.' : null;
      formErr = agreed ? null : 'Please agree to the Terms and the Privacy notice to continue.';
    });
    if (emailErr != null || pwErr != null || !agreed) return;
    setState(() => busy = true);
    final nav = Navigator.of(context);
    final addr = email.text.trim();
    try {
      await SessionScope.of(context).api.register(addr, pw.text);
      if (!mounted) return;
      setState(() => busy = false);
      nav.push(MaterialPageRoute<void>(builder: (_) => CheckEmailScreen(email: addr)));
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        busy = false;
        if (e.code == 'weak_password') {
          pwErr = e.message;
        } else if (e.code == 'bad_email') {
          emailErr = e.message;
        } else {
          formErr = e.message;
        }
      });
    }
  }

  @override
  void dispose() {
    email.dispose();
    pw.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final invited = SessionScope.of(context).pendingInvite != null;
    return CxScreen(children: [
      CxTop(title: invited ? 'Joining as a companion' : 'Step 1 of 3'),
      if (invited)
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(color: Cx.accent, borderRadius: BorderRadius.circular(Cx.tileRadius)),
          child: Row(children: [
            ExcludeSemantics(child: Container(width: 44, height: 44, decoration: const BoxDecoration(color: Cx.ground, shape: BoxShape.circle), child: const Icon(Icons.favorite, color: Cx.accent, size: 22))),
            const SizedBox(width: 14),
            const Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('You have been invited', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 16, fontWeight: FontWeight.w700, color: Cx.ground)),
              SizedBox(height: 2),
              Text('You will look after them as a companion.', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 13, fontWeight: FontWeight.w500, color: Cx.ground)),
            ])),
          ]),
        ),
      CxSpace(invited ? 6 : 26),
      CxTitle('Create\naccount', size: invited ? 48 : 52, height: .98),
      if (!invited) const CxText('One account for you, your glasses and the people you choose to share with.'),
      CxField(label: 'Email', controller: email, keyboard: TextInputType.emailAddress, autofill: const [AutofillHints.email], error: emailErr),
      CxField(
          label: 'Password',
          controller: pw,
          obscure: true,
          autofill: const [AutofillHints.newPassword],
          onSubmit: _submit,
          error: pwErr,
          help: invited ? 'At least 10 characters.' : 'At least 10 characters. A few random words works well.'),
      CxCheck(
          value: agreed,
          onChanged: (v) => setState(() => agreed = v),
          label: invited
              ? 'I agree to the Terms and the Privacy notice.'
              : 'I agree to the Terms and the Privacy notice. I understand the glasses never send camera images or video to Asirive.'),
      if (formErr != null) CxNotice(formErr!, error: true),
    ], bottom: [
      CxButton('Create account', onTap: _submit, busy: busy),
      Text(invited ? 'No glasses needed. We will email you a link to confirm this address.' : 'We will email you a link to confirm this address.', textAlign: TextAlign.center, style: Cx.small),
    ]);
  }
}

class CheckEmailScreen extends StatefulWidget {
  const CheckEmailScreen({super.key, required this.email});
  final String email;
  @override
  State<CheckEmailScreen> createState() => _CheckEmailScreenState();
}

class _CheckEmailScreenState extends State<CheckEmailScreen> {
  String? note;
  bool busy = false;

  Future<void> _resend() async {
    setState(() => busy = true);
    try {
      await SessionScope.of(context).api.resend(widget.email);
      note = 'Sent again. It can take a minute.';
    } on ApiException catch (e) {
      note = e.message;
    }
    if (mounted) setState(() => busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final invited = s.pendingInvite != null;
    return CxScreen(children: [
      CxTop(title: invited ? 'Joining as a companion' : 'Step 2 of 3'),
      const CxSpace(30),
      const CxIconTile(Icons.mail_outline),
      const CxSpace(10),
      const CxTitle('Check\nyour email', size: 52, height: .98),
      Text.rich(TextSpan(style: Cx.body, children: [
        const TextSpan(text: 'We sent a link to '),
        TextSpan(text: widget.email, style: const TextStyle(color: Cx.text, fontWeight: FontWeight.w700)),
        TextSpan(text: invited ? '. Open it on this phone. You will then see the person who invited you in your list.' : '. Open it on this phone to finish creating your account.'),
      ])),
      CxTile(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('GOOD TO KNOW', style: Cx.label),
        const SizedBox(height: 8),
        Text(invited ? 'The link expires after 24 hours. If you do not see it, look in spam.' : 'The link works once and expires after 24 hours. If you do not see it, look in spam.', style: Cx.body.copyWith(fontSize: 14)),
      ])),
      if (note != null) CxNotice(note!),
    ], bottom: [
      CxButton('Open mail app', onTap: () => s.services.opener.open(mailAppUri())),
      CxButton('Send the email again', outline: true, onTap: _resend, busy: busy),
      if (!invited) CxYellowLink('Use a different email', onTap: () => Navigator.of(context).maybePop()),
      CxYellowLink('I have confirmed, sign in', onTap: () => Navigator.of(context).pushReplacement(MaterialPageRoute<void>(builder: (_) => const SignInScreen()))),
    ]);
  }
}

class ForgotScreen extends StatefulWidget {
  const ForgotScreen({super.key, this.email = ''});
  final String email;
  @override
  State<ForgotScreen> createState() => _ForgotScreenState();
}

class _ForgotScreenState extends State<ForgotScreen> {
  late final email = TextEditingController(text: widget.email);
  String? err;
  bool busy = false;
  bool sent = false;

  Future<void> _submit() async {
    setState(() => err = _emailError(email.text));
    if (err != null) return;
    setState(() => busy = true);
    try {
      await SessionScope.of(context).api.resetRequest(email.text.trim());
      if (mounted) setState(() => sent = true);
    } on ApiException catch (e) {
      if (mounted) setState(() => err = e.message);
    }
    if (mounted) setState(() => busy = false);
  }

  @override
  void dispose() {
    email.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    if (sent) {
      return CxScreen(children: [
        CxTop(title: 'Reset password', onBack: () => setState(() => sent = false)),
        const CxSpace(30),
        const CxIconTile(Icons.mail_outline),
        const CxSpace(10),
        const CxTitle('Link\nsent', size: 52, height: .98),
        const CxText('If that email has an account, a link is on its way. It works for one hour.'),
      ], bottom: [
        CxButton('Open mail app', onTap: () => s.services.opener.open(mailAppUri())),
        CxButton('Use a different email', outline: true, onTap: () => setState(() => sent = false)),
        CxYellowLink('Back to sign in', onTap: () => Navigator.of(context).maybePop()),
      ]);
    }
    return CxScreen(children: [
      const CxTop(title: 'Reset password'),
      const CxSpace(26),
      const CxTitle('Forgot\npassword', size: 52, height: .98),
      const CxText('Enter your email. We will send a link to choose a new password.'),
      CxField(label: 'Email', controller: email, keyboard: TextInputType.emailAddress, onSubmit: _submit, error: err),
      const Padding(padding: EdgeInsets.symmetric(horizontal: 8), child: Text('We will email you a link to choose a new password.', style: Cx.small)),
    ], bottom: [
      CxButton('Send reset link', onTap: _submit, busy: busy),
      CxYellowLink('Back to sign in', onTap: () => Navigator.of(context).maybePop()),
    ]);
  }
}

/// Opened from the reset link in the email (asirive://reset?token=...).
class NewPasswordScreen extends StatefulWidget {
  const NewPasswordScreen({super.key, required this.token});
  final String token;
  @override
  State<NewPasswordScreen> createState() => _NewPasswordScreenState();
}

class _NewPasswordScreenState extends State<NewPasswordScreen> {
  final pw = TextEditingController();
  String? err;
  bool busy = false;

  Future<void> _save() async {
    if (pw.text.length < 10) {
      setState(() => err = 'Use at least 10 characters.');
      return;
    }
    setState(() {
      busy = true;
      err = null;
    });
    final nav = Navigator.of(context);
    try {
      await SessionScope.of(context).api.reset(widget.token, pw.text);
      nav.pushReplacement(MaterialPageRoute<void>(builder: (_) => const SignInScreen(notice: 'Password changed. Sign in with the new one.')));
    } on ApiException catch (e) {
      if (mounted) setState(() {
        err = e.message;
        busy = false;
      });
    }
  }

  @override
  void dispose() {
    pw.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => CxScreen(children: [
        const CxTop(back: false, title: 'Reset password'),
        const CxSpace(26),
        const CxTitle('New\npassword', size: 52, height: .98),
        const CxText('Choose a new password for your account.'),
        CxField(label: 'New password', controller: pw, obscure: true, autofill: const [AutofillHints.newPassword], onSubmit: _save, error: err, help: 'At least 10 characters.'),
      ], bottom: [
        CxButton('Save and sign in', onTap: _save, busy: busy),
        const Text('You will be signed out of other phones.', textAlign: TextAlign.center, style: Cx.small),
      ]);
}

/// Shown after the email link confirms the address.
class EmailConfirmedScreen extends StatelessWidget {
  const EmailConfirmedScreen({super.key, this.ok = true, this.message});
  final bool ok;
  final String? message;
  @override
  Widget build(BuildContext context) => CxScreen(children: [
        const CxTop(back: false, logo: true, title: 'Asirive Cortex'),
        const CxSpace(30),
        CxIconTile(ok ? Icons.check : Icons.error_outline),
        CxTitle(ok ? 'Email\nconfirmed' : 'Link\nproblem', size: 52, height: .98),
        CxText(ok ? 'Thank you. Sign in to carry on.' : (message ?? 'This link is invalid or has expired. Ask for a new one.')),
      ], bottom: [
        CxButton('Sign in', onTap: () => Navigator.of(context).pushReplacement(MaterialPageRoute<void>(builder: (_) => const SignInScreen()))),
      ]);
}

/// Shown once after the server ends a session.
class SignedOutScreen extends StatelessWidget {
  const SignedOutScreen({super.key});
  @override
  Widget build(BuildContext context) => CxScreen(children: [
        const CxTop(back: false, logo: true, title: 'Asirive Cortex'),
        const CxSpace(60),
        const CxTitle('You were\nsigned out', size: 52, height: .98),
        const Text('Sign in again to carry on. Your glasses keep working, and obstacle warnings are not affected.', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 17, height: 1.45, color: Cx.text)),
        CxTile(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('WHY THIS HAPPENS', style: Cx.label),
          const SizedBox(height: 6),
          Text('For safety, you stay signed in for 30 days. Changing your password also signs you out.', style: Cx.body.copyWith(fontSize: 14)),
        ])),
      ], bottom: [
        CxButton('Sign in', onTap: () => push(context, const SignInScreen())),
      ]);
}
