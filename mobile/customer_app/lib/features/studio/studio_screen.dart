import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/app_controller.dart';
import '../../core/l10n.dart';
import '../../core/models.dart';
import '../../ui/common.dart';
import '../cart/cart_screen.dart';

class StudioProjectsScreen extends StatefulWidget {
  const StudioProjectsScreen({super.key, required this.controller});
  final AppController controller;

  @override
  State<StudioProjectsScreen> createState() => _StudioProjectsScreenState();
}

class _StudioProjectsScreenState extends State<StudioProjectsScreen> {
  List<StudioProject> rows = [];
  bool loading = true;
  Object? error;

  @override
  void initState() { super.initState(); load(); }

  Future<void> load() async {
    setState(() { loading = true; error = null; });
    try {
      final first = await widget.controller.api.studioProjects();
      final all = <StudioProject>[...first.results];
      var page = 2;
      while (all.length < first.count) {
        final next = await widget.controller.api.studioProjects(page: page++);
        if (next.results.isEmpty) break;
        all.addAll(next.results);
      }
      if (mounted) setState(() => rows = all);
    } catch (value) {
      if (mounted) setState(() => error = value);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (loading) return const BusyView();
    if (error != null) return FailureView(error: error!, onRetry: load);
    if (rows.isEmpty) {
      return EmptyView(
        icon: Icons.auto_fix_high_outlined,
        title: L10n.t(context, 'noProjects'),
        message: L10n.t(context, 'studioHint'),
      );
    }
    return RefreshIndicator(
      onRefresh: load,
      child: ListView.separated(
        padding: const EdgeInsets.all(16),
        itemCount: rows.length,
        separatorBuilder: (_, __) => const SizedBox(height: 10),
        itemBuilder: (context, index) {
          final project = rows[index];
          return Card(
            child: ListTile(
              contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              leading: CircleAvatar(child: Icon(project.isReady ? Icons.check_rounded : Icons.edit_outlined)),
              title: Text(project.product.title, style: const TextStyle(fontWeight: FontWeight.w800)),
              subtitle: Text('${project.isReady ? L10n.t(context, 'ready') : L10n.t(context, 'draft')} · ${project.unitPrice.display}'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () async {
                await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => StudioEditorScreen(controller: widget.controller, initialProject: project)));
                load();
              },
            ),
          );
        },
      ),
    );
  }
}

class StudioEditorScreen extends StatefulWidget {
  const StudioEditorScreen({super.key, required this.controller, required this.initialProject});
  final AppController controller;
  final StudioProject initialProject;

  @override
  State<StudioEditorScreen> createState() => _StudioEditorScreenState();
}

class _StudioEditorScreenState extends State<StudioEditorScreen> {
  late StudioProject project = widget.initialProject;
  Product? product;
  List<StudioElement> elements = [];
  int? selectedElementId;
  bool loading = true;
  bool saving = false;
  Object? error;
  StudioTransform? gestureBase;

  @override
  void initState() { super.initState(); load(); }

  Future<void> load() async {
    setState(() { loading = true; error = null; });
    try {
      final results = await Future.wait([
        widget.controller.api.studioProject(project.id),
        widget.controller.api.product(project.product.storeSlug, project.product.productSlug),
      ]);
      if (!mounted) return;
      setState(() {
        project = results[0] as StudioProject;
        product = results[1] as Product;
        elements = [...project.elements];
      });
    } catch (value) {
      if (mounted) setState(() => error = value);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  DecorationZone? get selectedZone {
    final selected = elements.where((value) => value.id == selectedElementId);
    return selected.isEmpty ? null : selected.first.decorationZone;
  }

  Future<void> persistElement(StudioElement local) async {
    if (saving || !project.isDraft) return;
    setState(() => saving = true);
    try {
      final saved = await widget.controller.api.updateStudioElement(project.id, local.id, transform: local.transform, productionMethod: local.productionMethod, text: local.kind == 'text' ? local.text : null);
      if (!mounted) return;
      setState(() {
        final index = elements.indexWhere((item) => item.id == saved.id);
        if (index >= 0) elements[index] = saved;
      });
    } catch (value) {
      await load();
      if (mounted) await showProblem(context, value);
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  void transformLocal(StudioElement element, ScaleUpdateDetails details, Size zoneSize) {
    if (!project.isDraft || gestureBase == null) return;
    final currentIndex = elements.indexWhere((value) => value.id == element.id);
    if (currentIndex < 0) return;
    final current = elements[currentIndex];
    final movedX = (current.transform.x + details.focalPointDelta.dx / zoneSize.width).clamp(0.0, 1.0);
    final movedY = (current.transform.y + details.focalPointDelta.dy / zoneSize.height).clamp(0.0, 1.0);
    final scaled = (gestureBase!.scale * details.scale).clamp(.05, 1.0);
    final rotated = gestureBase!.rotation + details.rotation * 180 / math.pi;
    setState(() => elements[currentIndex] = current.copyWith(transform: current.transform.copyWith(x: movedX, y: movedY, scale: scaled, rotation: rotated)));
  }

  Future<_ElementChoice?> chooseZoneAndMethod({Artwork? artwork}) async {
    if (project.decorationZones.isEmpty) return null;
    DecorationZone zone = project.decorationZones.first;
    String method = zone.supportedMethods.first;
    return showDialog<_ElementChoice>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) {
          var allowed = zone.supportedMethods;
          if (artwork != null) allowed = allowed.where(artwork.productionMethods.contains).toList();
          if (allowed.isNotEmpty && !allowed.contains(method)) method = allowed.first;
          return AlertDialog(
            title: Text(L10n.t(context, 'zone')),
            content: Column(mainAxisSize: MainAxisSize.min, children: [
              DropdownButtonFormField<DecorationZone>(
                value: zone,
                decoration: InputDecoration(labelText: L10n.t(context, 'zone')),
                items: project.decorationZones.map((value) => DropdownMenuItem(value: value, child: Text(value.name))).toList(),
                onChanged: (value) {
                  if (value == null) return;
                  setDialogState(() { zone = value; method = value.supportedMethods.first; });
                },
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                value: allowed.contains(method) ? method : null,
                decoration: InputDecoration(labelText: L10n.t(context, 'productionMethod')),
                items: allowed.map((value) => DropdownMenuItem(value: value, child: Text(value == 'embroidery' ? L10n.t(context, 'embroidery') : L10n.t(context, 'print')))).toList(),
                onChanged: (value) { if (value != null) setDialogState(() => method = value); },
              ),
              if (allowed.isEmpty) Padding(padding: const EdgeInsets.only(top: 12), child: Text(L10n.t(context, 'unavailable'))),
            ]),
            actions: [
              TextButton(onPressed: () => Navigator.pop(context), child: Text(L10n.t(context, 'cancel'))),
              FilledButton(onPressed: allowed.isEmpty ? null : () => Navigator.pop(context, _ElementChoice(zone, method)), child: Text(L10n.t(context, 'continue'))),
            ],
          );
        },
      ),
    );
  }

  Future<void> addText() async {
    if (!project.isDraft) return;
    final text = TextEditingController();
    final value = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(L10n.t(context, 'addText')),
        content: TextField(controller: text, autofocus: true, maxLength: 120, decoration: InputDecoration(labelText: L10n.t(context, 'text'))),
        actions: [TextButton(onPressed: () => Navigator.pop(context), child: Text(L10n.t(context, 'cancel'))), FilledButton(onPressed: () => Navigator.pop(context, text.text.trim()), child: Text(L10n.t(context, 'continue')))],
      ),
    );
    text.dispose();
    if (value == null || value.isEmpty || !mounted) return;
    final choice = await chooseZoneAndMethod();
    if (choice == null) return;
    try {
      final element = await widget.controller.api.addStudioElement(project.id, zone: choice.zone.name, kind: 'text', text: value, productionMethod: choice.method, rightsConfirmed: false, sortOrder: elements.length);
      if (mounted) setState(() { elements.add(element); selectedElementId = element.id; });
    } catch (error) { if (mounted) await showProblem(context, error); }
  }

  Future<void> addArtwork() async {
    if (!project.isDraft) return;
    Artwork? selected;
    try {
      final result = await widget.controller.api.artworks();
      if (!mounted) return;
      selected = await showDialog<Artwork>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text(L10n.t(context, 'selectArtwork')),
          content: SizedBox(width: 520, height: 420, child: result.results.isEmpty ? EmptyView(icon: Icons.palette_outlined, title: L10n.t(context, 'noData')) : ListView.builder(itemCount: result.results.length, itemBuilder: (context, index) {
            final art = result.results[index];
            return ListTile(title: Text(art.title), subtitle: Text(art.creatorName), onTap: () => Navigator.pop(context, art));
          })),
          actions: [TextButton(onPressed: () => Navigator.pop(context), child: Text(L10n.t(context, 'cancel')))],
        ),
      );
    } catch (error) { if (mounted) await showProblem(context, error); return; }
    if (selected == null || !mounted) return;
    final choice = await chooseZoneAndMethod(artwork: selected);
    if (choice == null) return;
    try {
      final element = await widget.controller.api.addStudioElement(project.id, zone: choice.zone.name, kind: 'artwork', artworkVersionId: selected.approvedVersionId, productionMethod: choice.method, rightsConfirmed: false, sortOrder: elements.length);
      if (mounted) setState(() { elements.add(element); selectedElementId = element.id; });
    } catch (error) { if (mounted) await showProblem(context, error); }
  }

  Future<void> uploadImage() async {
    if (!project.isDraft) return;
    final picked = await ImagePicker().pickImage(source: ImageSource.gallery);
    if (picked == null) return;
    final lower = picked.name.toLowerCase();
    if (!(lower.endsWith('.png') || lower.endsWith('.jpg') || lower.endsWith('.jpeg') || lower.endsWith('.webp'))) {
      if (mounted) await showDialog<void>(context: context, builder: (context) => AlertDialog(content: Text(L10n.t(context, 'unsupportedImage')), actions: [TextButton(onPressed: () => Navigator.pop(context), child: Text(L10n.t(context, 'close')))]));
      return;
    }
    final bytes = await picked.readAsBytes();
    if (bytes.length > 10485760) {
      if (mounted) await showDialog<void>(context: context, builder: (context) => AlertDialog(content: Text(L10n.t(context, 'fileTooLarge')), actions: [TextButton(onPressed: () => Navigator.pop(context), child: Text(L10n.t(context, 'close')))]));
      return;
    }
    if (!mounted) return;
    final choice = await chooseZoneAndMethod();
    if (choice == null || !mounted) return;
    var confirmed = false;
    final rights = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(builder: (context, setDialogState) => AlertDialog(
        title: Text(L10n.t(context, 'uploadImage')),
        content: CheckboxListTile(contentPadding: EdgeInsets.zero, value: confirmed, onChanged: (value) => setDialogState(() => confirmed = value ?? false), title: Text(L10n.t(context, 'rightsConfirm'))),
        actions: [TextButton(onPressed: () => Navigator.pop(context), child: Text(L10n.t(context, 'cancel'))), FilledButton(onPressed: confirmed ? () => Navigator.pop(context, true) : null, child: Text(L10n.t(context, 'continue')))],
      )),
    );
    if (rights != true) return;
    setState(() => saving = true);
    try {
      final upload = await widget.controller.api.uploadStudioImage(project.id, bytes, picked.name);
      final element = await widget.controller.api.addStudioElement(project.id, zone: choice.zone.name, kind: 'image', mediaAssetId: upload.id, productionMethod: choice.method, rightsConfirmed: true, sortOrder: elements.length);
      if (mounted) setState(() { elements.add(element); selectedElementId = element.id; });
    } catch (error) { if (mounted) await showProblem(context, error); }
    finally { if (mounted) setState(() => saving = false); }
  }

  Future<void> deleteSelected() async {
    final id = selectedElementId;
    if (id == null || !project.isDraft) return;
    try {
      await widget.controller.api.deleteStudioElement(project.id, id);
      if (mounted) setState(() { elements.removeWhere((value) => value.id == id); selectedElementId = null; });
    } catch (error) { if (mounted) await showProblem(context, error); }
  }

  Future<void> validateAndReady() async {
    setState(() => saving = true);
    try {
      final validation = await widget.controller.api.validateStudio(project.id);
      if (!mounted) return;
      if (!validation.valid) {
        await showDialog<void>(context: context, builder: (context) => AlertDialog(title: Text(L10n.t(context, 'validationFailed')), content: Text(validation.errors.join('\n')), actions: [TextButton(onPressed: () => Navigator.pop(context), child: Text(L10n.t(context, 'close')))]));
        return;
      }
      final ready = await widget.controller.api.markStudioReady(project.id);
      if (mounted) setState(() { project = ready; elements = [...ready.elements]; });
    } catch (error) { if (mounted) await showProblem(context, error); }
    finally { if (mounted) setState(() => saving = false); }
  }

  Future<void> addReadyToCart() async {
    try {
      await widget.controller.api.addCartItem(kind: 'studio', studioProjectId: project.id, quantity: project.quantity);
      if (mounted) await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => CartScreen(controller: widget.controller)));
    } catch (error) { if (mounted) await showProblem(context, error); }
  }

  Future<void> directCheckout() async {
    try {
      final checkout = await widget.controller.api.studioCheckout(project.id);
      if (mounted) await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => CheckoutScreen(controller: widget.controller, initialCheckout: checkout)));
    } catch (error) { if (mounted) await showProblem(context, error); }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text(project.product.title),
      actions: [if (saving) const Padding(padding: EdgeInsets.symmetric(horizontal: 16), child: Center(child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))))],
    ),
    body: loading ? const BusyView() : error != null ? FailureView(error: error!, onRetry: load) : LayoutBuilder(builder: (context, constraints) {
      final wide = constraints.maxWidth >= 850;
      final canvas = _StudioCanvas(
        controller: widget.controller,
        product: product!,
        project: project,
        elements: elements,
        selectedId: selectedElementId,
        onSelect: (id) => setState(() => selectedElementId = id),
        onGestureStart: (element) => gestureBase = element.transform,
        onGestureUpdate: transformLocal,
        onGestureEnd: (element) { gestureBase = null; persistElement(element); },
      );
      final tools = _toolPanel(context);
      return wide ? Row(children: [Expanded(flex: 7, child: canvas), SizedBox(width: 360, child: tools)]) : Column(children: [Expanded(child: canvas), SizedBox(height: 250, child: tools)]);
    }),
  );

  Widget _toolPanel(BuildContext context) => Material(
    color: Theme.of(context).colorScheme.surfaceContainerLow,
    child: ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(children: [Expanded(child: Text(project.isReady ? L10n.t(context, 'ready') : L10n.t(context, 'draft'), style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w900))), MoneyText(project.unitPrice)]),
        const SizedBox(height: 12),
        if (project.isDraft) ...[
          Wrap(spacing: 8, runSpacing: 8, children: [
            FilledButton.tonalIcon(onPressed: saving ? null : addText, icon: const Icon(Icons.text_fields), label: Text(L10n.t(context, 'addText'))),
            FilledButton.tonalIcon(onPressed: saving ? null : addArtwork, icon: const Icon(Icons.palette_outlined), label: Text(L10n.t(context, 'addArtwork'))),
            FilledButton.tonalIcon(onPressed: saving ? null : uploadImage, icon: const Icon(Icons.add_photo_alternate_outlined), label: Text(L10n.t(context, 'uploadImage'))),
          ]),
          if (selectedElementId != null) ...[const Divider(height: 28), OutlinedButton.icon(onPressed: saving ? null : deleteSelected, icon: const Icon(Icons.delete_outline), label: Text(L10n.t(context, 'delete')))],
          const Divider(height: 28),
          FilledButton.icon(onPressed: saving ? null : validateAndReady, icon: const Icon(Icons.verified_outlined), label: Text(L10n.t(context, 'markReady'))),
        ] else ...[
          Text(L10n.t(context, 'readyForCart')),
          const SizedBox(height: 12),
          FilledButton.icon(onPressed: saving ? null : addReadyToCart, icon: const Icon(Icons.shopping_bag_outlined), label: Text(L10n.t(context, 'addToCart'))),
          const SizedBox(height: 8),
          OutlinedButton.icon(onPressed: saving ? null : directCheckout, icon: const Icon(Icons.payment_outlined), label: Text(L10n.t(context, 'checkout'))),
        ],
      ],
    ),
  );
}

class _StudioCanvas extends StatelessWidget {
  const _StudioCanvas({required this.controller, required this.product, required this.project, required this.elements, required this.selectedId, required this.onSelect, required this.onGestureStart, required this.onGestureUpdate, required this.onGestureEnd});
  final AppController controller;
  final Product product;
  final StudioProject project;
  final List<StudioElement> elements;
  final int? selectedId;
  final ValueChanged<int?> onSelect;
  final ValueChanged<StudioElement> onGestureStart;
  final void Function(StudioElement, ScaleUpdateDetails, Size) onGestureUpdate;
  final ValueChanged<StudioElement> onGestureEnd;

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: AspectRatio(
        aspectRatio: 1,
        child: Card(
          clipBehavior: Clip.antiAlias,
          elevation: 2,
          child: LayoutBuilder(builder: (context, constraints) {
            final size = Size(constraints.maxWidth, constraints.maxHeight);
            final image = product.images.isEmpty ? null : product.images.first;
            return GestureDetector(
              onTap: () => onSelect(null),
              child: Stack(children: [
                Positioned.fill(child: image == null || image.url.isEmpty ? ColoredBox(color: Theme.of(context).colorScheme.surfaceContainerHighest) : Image.network(controller.config.resolveApplicationUrl(image.url).toString(), fit: BoxFit.contain, errorBuilder: (_, __, ___) => ColoredBox(color: Theme.of(context).colorScheme.surfaceContainerHighest))),
                ...project.decorationZones.map((zone) => _zone(context, zone, size)),
              ]),
            );
          }),
        ),
      ),
    ),
  );

  Widget _zone(BuildContext context, DecorationZone zone, Size canvas) {
    final rect = Rect.fromLTWH(zone.placement.x * canvas.width, zone.placement.y * canvas.height, zone.placement.width * canvas.width, zone.placement.height * canvas.height);
    final zoneElements = elements.where((element) => element.decorationZone.name == zone.name).toList();
    return Positioned(
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height,
      child: LayoutBuilder(builder: (context, constraints) {
        final zoneSize = Size(constraints.maxWidth, constraints.maxHeight);
        return Stack(clipBehavior: Clip.none, children: [
          Positioned.fill(child: IgnorePointer(child: DecoratedBox(decoration: BoxDecoration(border: Border.all(color: Theme.of(context).colorScheme.primary.withValues(alpha: .35), width: 1.5), color: Theme.of(context).colorScheme.primary.withValues(alpha: .035))))),
          Positioned(left: 6, top: 4, child: IgnorePointer(child: Text(zone.name, style: Theme.of(context).textTheme.labelSmall?.copyWith(color: Theme.of(context).colorScheme.primary)))),
          ...zoneElements.map((element) => _element(context, element, zoneSize)),
        ]);
      }),
    );
  }

  Widget _element(BuildContext context, StudioElement element, Size zoneSize) {
    final extent = element.transform.scale * math.min(zoneSize.width, zoneSize.height);
    final left = element.transform.x * zoneSize.width - extent / 2;
    final top = element.transform.y * zoneSize.height - extent / 2;
    final selected = selectedId == element.id;
    final display = switch (element.kind) {
      'text' => Center(child: Text(element.text, textAlign: TextAlign.center, maxLines: 3, style: TextStyle(fontSize: math.max(10, extent * .18), fontWeight: FontWeight.w800))),
      'image' when element.sourceUrl != null => ProtectedImage(controller: controller, url: element.sourceUrl!),
      'artwork' when element.sourceUrl != null => Image.network(controller.config.resolveApplicationUrl(element.sourceUrl!).toString(), fit: BoxFit.contain, errorBuilder: (_, __, ___) => const Icon(Icons.broken_image_outlined)),
      _ => const Center(child: Icon(Icons.image_outlined)),
    };
    return Positioned(
      left: left,
      top: top,
      width: extent,
      height: extent,
      child: Transform.rotate(
        angle: element.transform.rotation * math.pi / 180,
        child: GestureDetector(
          onTap: () => onSelect(element.id),
          onScaleStart: (_) { onSelect(element.id); onGestureStart(element); },
          onScaleUpdate: (details) => onGestureUpdate(element, details, zoneSize),
          onScaleEnd: (_) {
            final current = elements.where((value) => value.id == element.id).firstOrNull;
            if (current != null) onGestureEnd(current);
          },
          child: Semantics(
            button: true,
            label: '${element.kind} · ${L10n.t(context, 'moveResizeRotate')}',
            child: DecoratedBox(decoration: BoxDecoration(border: Border.all(color: selected ? Theme.of(context).colorScheme.secondary : Colors.transparent, width: 2), color: selected ? Theme.of(context).colorScheme.surface.withValues(alpha: .35) : Colors.transparent), child: display),
          ),
        ),
      ),
    );
  }
}

class _ElementChoice {
  const _ElementChoice(this.zone, this.method);
  final DecorationZone zone;
  final String method;
}

extension _FirstOrNullStudio<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
