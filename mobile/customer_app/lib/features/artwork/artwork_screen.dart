import 'package:flutter/material.dart';

import '../../core/app_controller.dart';
import '../../core/l10n.dart';
import '../../core/models.dart';
import '../../ui/common.dart';

class ArtworkScreen extends StatefulWidget {
  const ArtworkScreen({super.key, required this.controller});
  final AppController controller;

  @override
  State<ArtworkScreen> createState() => _ArtworkScreenState();
}

class _ArtworkScreenState extends State<ArtworkScreen> {
  final search = TextEditingController();
  final scroll = ScrollController();
  String method = '';
  List<Artwork> rows = [];
  int page = 1;
  int total = 0;
  bool loading = true;
  bool loadingMore = false;
  Object? error;

  @override
  void initState() {
    super.initState();
    scroll.addListener(_scroll);
    load();
  }

  @override
  void dispose() {
    search.dispose();
    scroll.dispose();
    super.dispose();
  }

  void _scroll() {
    if (scroll.position.pixels > scroll.position.maxScrollExtent - 400 &&
        rows.length < total &&
        !loadingMore)
      loadMore();
  }

  Future<void> load() async {
    setState(() {
      loading = true;
      error = null;
      page = 1;
    });
    try {
      final result = await widget.controller.api.artworks(
        query: search.text.trim(),
        method: method,
      );
      if (mounted)
        setState(() {
          rows = result.results;
          total = result.count;
        });
    } catch (value) {
      if (mounted) setState(() => error = value);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> loadMore() async {
    setState(() => loadingMore = true);
    try {
      final result = await widget.controller.api.artworks(
        query: search.text.trim(),
        method: method,
        page: page + 1,
      );
      if (mounted)
        setState(() {
          page++;
          rows.addAll(result.results);
          total = result.count;
        });
    } finally {
      if (mounted) setState(() => loadingMore = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (loading) return const BusyView();
    if (error != null) return FailureView(error: error!, onRetry: load);
    return RefreshIndicator(
      onRefresh: load,
      child: ListView(
        controller: scroll,
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16),
        children: [
          SearchBar(
            controller: search,
            hintText: L10n.t(context, 'search'),
            leading: const Icon(Icons.search),
            onSubmitted: (_) => load(),
          ),
          const SizedBox(height: 10),
          SegmentedButton<String>(
            segments: [
              ButtonSegment(value: '', label: Text(L10n.t(context, 'all'))),
              ButtonSegment(
                value: 'print',
                label: Text(L10n.t(context, 'print')),
              ),
              ButtonSegment(
                value: 'embroidery',
                label: Text(L10n.t(context, 'embroidery')),
              ),
            ],
            selected: {method},
            onSelectionChanged: (value) {
              setState(() => method = value.first);
              load();
            },
          ),
          const SizedBox(height: 16),
          if (rows.isEmpty)
            SizedBox(
              height: 420,
              child: EmptyView(
                icon: Icons.palette_outlined,
                title: L10n.t(context, 'noData'),
              ),
            )
          else
            ...rows.map(
              (art) => Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Card(
                  clipBehavior: Clip.antiAlias,
                  child: InkWell(
                    onTap: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => ArtworkDetailScreen(
                          controller: widget.controller,
                          artwork: art,
                        ),
                      ),
                    ),
                    child: Row(
                      children: [
                        SizedBox(
                          width: 120,
                          height: 120,
                          child: PublicImage(image: art.preview, height: 120),
                        ),
                        Expanded(
                          child: Padding(
                            padding: const EdgeInsets.all(14),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  art.title,
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                  style: Theme.of(context).textTheme.titleMedium
                                      ?.copyWith(fontWeight: FontWeight.w800),
                                ),
                                const SizedBox(height: 5),
                                Text(
                                  art.creatorName,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                ),
                                const SizedBox(height: 8),
                                Wrap(
                                  spacing: 5,
                                  children: art.productionMethods
                                      .map(
                                        (value) => Chip(
                                          label: Text(
                                            value == 'embroidery'
                                                ? L10n.t(context, 'embroidery')
                                                : L10n.t(context, 'print'),
                                          ),
                                          visualDensity: VisualDensity.compact,
                                        ),
                                      )
                                      .toList(),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          if (loadingMore)
            const Padding(
              padding: EdgeInsets.all(20),
              child: Center(child: CircularProgressIndicator()),
            ),
        ],
      ),
    );
  }
}

class ArtworkDetailScreen extends StatefulWidget {
  const ArtworkDetailScreen({
    super.key,
    required this.controller,
    required this.artwork,
  });
  final AppController controller;
  final Artwork artwork;
  @override
  State<ArtworkDetailScreen> createState() => _ArtworkDetailScreenState();
}

class _ArtworkDetailScreenState extends State<ArtworkDetailScreen> {
  Artwork? detail;
  Object? error;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final value = await widget.controller.api.artwork(widget.artwork.id);
      if (mounted) setState(() => detail = value);
    } catch (value) {
      if (mounted) setState(() => error = value);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(widget.artwork.title)),
    body: error != null
        ? FailureView(error: error!, onRetry: load)
        : detail == null
        ? const BusyView()
        : ListView(
            padding: const EdgeInsets.only(bottom: 28),
            children: [
              PublicImage(
                image: detail!.preview,
                height: 360,
                fit: BoxFit.contain,
              ),
              Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      detail!.title,
                      style: Theme.of(context).textTheme.headlineSmall
                          ?.copyWith(fontWeight: FontWeight.w900),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      detail!.creatorName,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    if (detail!.description.isNotEmpty) ...[
                      const SizedBox(height: 18),
                      Text(detail!.description),
                    ],
                    const SizedBox(height: 18),
                    Text(
                      L10n.t(context, 'productionMethod'),
                      style: Theme.of(context).textTheme.titleMedium
                          ?.copyWith(fontWeight: FontWeight.w800),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      children: detail!.productionMethods
                          .map(
                            (value) => Chip(
                              label: Text(
                                value == 'embroidery'
                                    ? L10n.t(context, 'embroidery')
                                    : L10n.t(context, 'print'),
                              ),
                            ),
                          )
                          .toList(),
                    ),
                    if (detail!.tags.isNotEmpty) ...[
                      const SizedBox(height: 18),
                      Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: detail!.tags
                            .map((tag) => Chip(label: Text(tag)))
                            .toList(),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
  );
}
