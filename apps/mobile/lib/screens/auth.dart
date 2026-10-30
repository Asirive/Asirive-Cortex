import 'package:flutter/material.dart';

import '../api.dart';
import '../scope.dart';
import '../theme.dart';
import '../widgets.dart';

final _emailRe = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');

String? _emailError(String v) =>
    _emailRe.hasMatch(v.trim()) ? null : "That doesn't look like an email address.";

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
        const CxTop(),
        const CxTitle('Welcome\nback'),
        if (widget.notice != null) CxText(widget.notice!, color: Cx.text),
        CxField(
            label: 'Email',
            controller: email,
            keyboard: TextInputType.emailAddress,
            autofill: const [AutofillHints.email],
            error: emailErr),
        CxField(
            label: 'Password',
            controller: pw,
            obscure: true,
            autofill: const [AutofillHints.password],
            onSubmit: _submit,
            error: formErr),
        if (unverified)
          CxLink('Send the confirmation email again', onTap: () async {
            try {
              await SessionScope.of(context).api.resend(email.text.trim());
              if (!mounted) return;
              setState(() => formErr = 'Sent. Check your email.');
            } on ApiException catch (e) {
              if (!mounted) return;
              setState(() => formErr = e.message);
            }
          }),
        CxButton('Sign in', onTap: _submit, busy: busy),
        CxLink('Forgot your password?',
            onTap: () => Navigator.of(context)
                .push(MaterialPageRoute<void>(builder: (_) => ForgotScreen(email: email.text)))),
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

  Future<void> _submit() async {
    setState(() {
      emailErr = _emailError(email.text);
      pwErr = pw.text.length < 10 ? 'Use at least 10 characters.' : null;
      formErr = null;
    });
    if (emailErr != null || pwErr != null) return;
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
  Widget build(BuildContext context) => CxScreen(children: [
        const CxTop(),
        const CxTitle('Make your\naccount'),
        const CxText('One account for the app. You can add glasses and people after.'),
        CxField(
            label: 'Email',
            controller: email,
            keyboard: TextInputType.emailAddress,
            autofill: const [AutofillHints.email],
            error: emailErr),
        CxField(
            label: 'Password',
            controller: pw,
            obscure: true,
            autofill: const [AutofillHints.newPassword],
            onSubmit: _submit,
            error: pwErr,
            help: 'At least 10 characters. A few random words works well.'),
        if (formErr != null) CxText(formErr!, color: Cx.danger),
        CxButton('Create account', onTap: _submit, busy: busy),
      ]);
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
  Widget build(BuildContext context) => CxScreen(children: [
        const CxTop(),
        const CxTitle('Check your\nemail'),
        CxText('We sent a link to ${widget.email}. Open it on this phone to confirm, then sign in.'),
        CxButton('Go to sign in',
            onTap: () => Navigator.of(context).pushReplacement(MaterialPageRoute<void>(
                builder: (_) => const SignInScreen()))),
        CxButton('Send it again', outline: true, onTap: _resend, busy: busy),
        if (note != null)
          Semantics(liveRegion: true, child: CxText(note!, small: true)),
      ]);
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
  Widget build(BuildContext context) => CxScreen(children: [
        const CxTop(),
        CxTitle(sent ? 'Check your\nemail' : 'Reset your\npassword'),
        if (sent)
          const CxText(
              'If there is an account for that address, a link is on its way. It works for one hour.')
        else ...[
          const CxText('Enter the email you signed up with and we will send a link.'),
          CxField(
              label: 'Email',
              controller: email,
              keyboard: TextInputType.emailAddress,
              onSubmit: _submit,
              error: err),
          CxButton('Send the link', onTap: _submit, busy: busy),
        ],
      ]);
}

/// Shown once after the server ends a session.
class SignedOutScreen extends StatelessWidget {
  const SignedOutScreen({super.key});
  @override
  Widget build(BuildContext context) => CxScreen(children: [
        const CxTop(back: false, trailing: CxLogo()),
        const CxTitle('You were\nsigned out'),
        const CxText('For your safety, Cortex signed you out. Sign in again to carry on.'),
        CxButton('Sign in',
            onTap: () => Navigator.of(context)
                .push(MaterialPageRoute<void>(builder: (_) => const SignInScreen()))),
      ]);
}
