import 'package:flutter/material.dart';

import '../../core/app_controller.dart';
import '../../core/l10n.dart';
import '../../core/models.dart';
import '../../ui/common.dart';
import '../studio/studio_screen.dart';

class DiscoverScreen extends StatefulWidget {
  const DiscoverScreen({
    super.key,
    required this.controller,
    required this.requestSignIn,
  });
  final AppController controller;
  final Future<bool> Function() requestSignIn;

  @override
  State<DiscoverScreen> createState() => _DiscoverScreenState();
}

class _DiscoverScreenState extends State<DiscoverScreen> {
  final search = TextEditingController();
  final scroll = ScrollController();
  List<Storefront> stores = [];
  List<Product> products = [];
  int page = 1;
  int total = 0;
  bool loading = true;
  bool loadingMore = false;
  Object? error;

  @override
  void initState() {
    super.initState();
    scroll.addListener(_onScroll);
    load();
  }

  @override
  void dispose() {
    search.dispose();
    scroll.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (scroll.position.pixels > scroll.position.maxScrollExtent - 500 &&
        !loadingMore &&
        products.length < total)
      loadMore();
  }

  Future<void> load() async {
    setState(() {
      loading = true;
      error = null;
      page = 1;
    });
    try {
      final results = await Future.wait([
        widget.controller.api.stores(query: search.text.trim()),
        widget.controller.api.products(query: search.text.trim()),
      ]);
      if (!mounted) return;
      final storePage = results[0] as Paged<Storefront>;
      final productPage = results[1] as Paged<Product>;
      setState(() {
        stores = storePage.results;
        products = productPage.results;
        total = productPage.count;
      });
    } catch (value) {
      if (mounted) setState(() => error = value);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> loadMore() async {
    if (loadingMore || products.length >= total) return;
    setState(() => loadingMore = true);
    try {
      final next = await widget.controller.api.products(
        query: search.text.trim(),
        page: page + 1,
      );
      if (!mounted) return;
      setState(() {
        page++;
        products.addAll(next.results);
        total = next.count;
      });
    } catch (_) {
      // Keep the already loaded catalog intact. A pull-to-refresh gives an explicit retry.
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
      child: CustomScrollView(
        controller: scroll,
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 10),
            sliver: SliverToBoxAdapter(
              child: SearchBar(
                controller: search,
                hintText: L10n.t(context, 'search'),
                leading: const Icon(Icons.search),
                trailing: search.text.isEmpty
                    ? null
                    : [
                        IconButton(
                          onPressed: () {
                            search.clear();
                            load();
                          },
                          icon: const Icon(Icons.clear),
                        ),
                      ],
                onSubmitted: (_) => load(),
              ),
            ),
          ),
          if (stores.isNotEmpty)
            SliverToBoxAdapter(
              child: SizedBox(
                height: 70,
                child: ListView.separated(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16,
                    vertical: 8,
                  ),
                  scrollDirection: Axis.horizontal,
                  itemCount: stores.length,
                  separatorBuilder: (_, __) => const SizedBox(width: 8),
                  itemBuilder: (context, index) => ActionChip(
                    avatar: const Icon(Icons.storefront_outlined, size: 18),
                    label: Text(stores[index].name),
                    onPressed: () async {
                      search.text = stores[index].name;
                      setState(() {
                        loading = true;
                        error = null;
                        page = 1;
                      });
                      try {
                        final result = await widget.controller.api.products(
                          store: stores[index].slug,
                        );
                        if (mounted)
                          setState(() {
                            products = result.results;
                            total = result.count;
                          });
                      } catch (value) {
                        if (mounted) setState(() => error = value);
                      } finally {
                        if (mounted) setState(() => loading = false);
                      }
                    },
                  ),
                ),
              ),
            ),
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 16),
            sliver: products.isEmpty
                ? SliverFillRemaining(
                    hasScrollBody: false,
                    child: EmptyView(
                      icon: Icons.inventory_2_outlined,
                      title: L10n.t(context, 'noData'),
                    ),
                  )
                : SliverLayoutBuilder(
                    builder: (context, constraints) {
                      final columns = constraints.crossAxisExtent >= 900
                          ? 3
                          : constraints.crossAxisExtent >= 600
                          ? 2
                          : 1;
                      return SliverGrid(
                        gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                          crossAxisCount: columns,
                          mainAxisSpacing: 14,
                          crossAxisSpacing: 14,
                          childAspectRatio: columns == 1 ? 1.45 : .78,
                        ),
                        delegate: SliverChildBuilderDelegate(
                          (context, index) => _ProductCard(
                            product: products[index],
                            onTap: () => Navigator.of(context).push(
                              MaterialPageRoute<void>(
                                builder: (_) => ProductDetailScreen(
                                  controller: widget.controller,
                                  product: products[index],
                                  requestSignIn: widget.requestSignIn,
                                ),
                              ),
                            ),
                          ),
                          childCount: products.length,
                        ),
                      );
                    },
                  ),
          ),
          if (loadingMore)
            const SliverToBoxAdapter(
              child: Padding(
                padding: EdgeInsets.all(20),
                child: Center(child: CircularProgressIndicator()),
              ),
            ),
        ],
      ),
    );
  }
}

class _ProductCard extends StatelessWidget {
  const _ProductCard({required this.product, required this.onTap});
  final Product product;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Card(
    clipBehavior: Clip.antiAlias,
    child: InkWell(
      onTap: onTap,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final horizontal =
              constraints.maxWidth > constraints.maxHeight * 1.25;
          final image = PublicImage(
            image: product.images.isEmpty ? null : product.images.first,
            height: horizontal ? constraints.maxHeight : 180,
          );
          final details = Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  product.storeName,
                  style: Theme.of(context).textTheme.labelMedium,
                ),
                const SizedBox(height: 4),
                Text(
                  product.title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.titleMedium
                      ?.copyWith(fontWeight: FontWeight.w800),
                ),
                const Spacer(),
                MoneyText(
                  product.variants.isNotEmpty
                      ? product.variants.first.price
                      : product.basePrice,
                ),
                if (product.customizationEnabled)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Row(
                      children: [
                        const Icon(Icons.auto_fix_high, size: 16),
                        const SizedBox(width: 4),
                        Text(L10n.t(context, 'customizable')),
                      ],
                    ),
                  ),
              ],
            ),
          );
          return horizontal
              ? Row(
                  children: [
                    Expanded(flex: 4, child: image),
                    Expanded(flex: 5, child: details),
                  ],
                )
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    image,
                    Expanded(child: details),
                  ],
                );
        },
      ),
    ),
  );
}

class ProductDetailScreen extends StatefulWidget {
  const ProductDetailScreen({
    super.key,
    required this.controller,
    required this.product,
    required this.requestSignIn,
  });
  final AppController controller;
  final Product product;
  final Future<bool> Function() requestSignIn;

  @override
  State<ProductDetailScreen> createState() => _ProductDetailScreenState();
}

class _ProductDetailScreenState extends State<ProductDetailScreen> {
  Product? detail;
  ProductVariant? selected;
  Object? error;
  bool busy = true;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final value = await widget.controller.api.product(
        widget.product.storeSlug,
        widget.product.slug,
      );
      if (!mounted) return;
      setState(() {
        detail = value;
        selected = value.variants.where((v) => v.available).firstOrNull;
      });
    } catch (value) {
      if (mounted) setState(() => error = value);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> addToCart() async {
    final item = detail;
    final variant = selected;
    if (item == null || variant == null || !await widget.requestSignIn())
      return;
    try {
      await widget.controller.api.addCartItem(
        kind: item.kind,
        storeSlug: item.storeSlug,
        productSlug: item.slug,
        variantSku: variant.sku,
      );
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(L10n.t(context, 'addToCart'))));
    } catch (error) {
      if (mounted) await showProblem(context, error);
    }
  }

  Future<void> customize() async {
    final item = detail;
    final variant = selected;
    if (item == null ||
        variant == null ||
        !item.customizationEnabled ||
        !await widget.requestSignIn())
      return;
    try {
      final project = await widget.controller.api.createStudio(
        storeSlug: item.storeSlug,
        productSlug: item.slug,
        variantSku: variant.sku,
      );
      if (mounted)
        await Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => StudioEditorScreen(
              controller: widget.controller,
              initialProject: project,
            ),
          ),
        );
    } catch (error) {
      if (mounted) await showProblem(context, error);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(widget.product.title)),
    body: busy
        ? const BusyView()
        : error != null
        ? FailureView(error: error!, onRetry: load)
        : _body(context),
  );

  Widget _body(BuildContext context) {
    final item = detail!;
    final image = item.images.isEmpty ? null : item.images.first;
    return ListView(
      padding: const EdgeInsets.only(bottom: 32),
      children: [
        PublicImage(image: image, height: 320, fit: BoxFit.contain),
        Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                item.storeName,
                style: Theme.of(context).textTheme.labelLarge,
              ),
              const SizedBox(height: 6),
              Text(
                item.title,
                style: Theme.of(context).textTheme.headlineSmall
                    ?.copyWith(fontWeight: FontWeight.w900),
              ),
              if (item.description.isNotEmpty) ...[
                const SizedBox(height: 12),
                Text(item.description),
              ],
              const SizedBox(height: 22),
              Text(
                L10n.t(context, 'variants'),
                style: Theme.of(context).textTheme.titleMedium
                    ?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: item.variants
                    .map(
                      (variant) => ChoiceChip(
                        label: Text(
                          [
                            variant.size,
                            variant.colorName,
                          ].where((v) => v.isNotEmpty).join(' · '),
                        ),
                        selected: selected?.sku == variant.sku,
                        onSelected: variant.available
                            ? (_) => setState(() => selected = variant)
                            : null,
                      ),
                    )
                    .toList(),
              ),
              const SizedBox(height: 20),
              MoneyText(
                selected?.price ?? item.basePrice,
                style: Theme.of(context).textTheme.headlineSmall
                    ?.copyWith(fontWeight: FontWeight.w900),
              ),
              if (item.leadTimeDays != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    '${L10n.t(context, 'leadTime')}: ${item.leadTimeDays} ${L10n.t(context, 'days')}',
                  ),
                ),
              const SizedBox(height: 24),
              Row(
                children: [
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: selected == null ? null : addToCart,
                      icon: const Icon(Icons.shopping_bag_outlined),
                      label: Text(L10n.t(context, 'addToCart')),
                    ),
                  ),
                  if (item.customizationEnabled) ...[
                    const SizedBox(width: 10),
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: selected == null ? null : customize,
                        icon: const Icon(Icons.auto_fix_high),
                        label: Text(L10n.t(context, 'customize')),
                      ),
                    ),
                  ],
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }
}

extension _FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
